from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from factory.general_agent_contracts import (
    Permission,
    ToolRequest,
)


ToolHandler = Callable[
    [dict[str, Any], str | None],
    Any,
]


@dataclass(frozen=True)
class ToolDefinition:
    # Modelin gorecegi tool sozlesmesi.
    name: str
    description: str
    permission: Permission
    input_schema: dict[str, Any]
    handler: ToolHandler | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "Tool name bos olamaz."
            )

        if not self.description.strip():
            raise ValueError(
                "Tool description bos olamaz."
            )

        if not isinstance(
            self.input_schema,
            dict,
        ):
            raise TypeError(
                "Tool input_schema dict olmali."
            )


class ToolRegistryError(RuntimeError):
    pass


class ToolNotFoundError(
    ToolRegistryError
):
    pass


class ToolPermissionError(
    ToolRegistryError
):
    pass


class ToolValidationError(
    ToolRegistryError
):
    pass


class ToolRegistry:
    def __init__(
        self,
        tools: Iterable[
            ToolDefinition
        ] = (),
    ) -> None:
        self._tools: dict[
            str,
            ToolDefinition,
        ] = {}

        for tool in tools:
            self.register(tool)

    def register(
        self,
        tool: ToolDefinition,
    ) -> None:
        key = tool.name.strip()

        if key in self._tools:
            raise ToolRegistryError(
                f"Tool zaten kayitli: {key}"
            )

        self._tools[key] = tool

    def has(
        self,
        name: str,
    ) -> bool:
        return name in self._tools

    def get(
        self,
        name: str,
    ) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(
                f"Tool bulunamadi: {name}"
            ) from exc

    def names(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                self._tools.keys()
            )
        )

    def definitions(
        self,
    ) -> tuple[
        ToolDefinition,
        ...,
    ]:
        return tuple(
            self._tools[name]
            for name in self.names()
        )

    def describe_for_model(
        self,
    ) -> list[dict[str, Any]]:
        # Handler bilgisi modele acilmaz.
        return [
            {
                "name": tool.name,
                "description": (
                    tool.description
                ),
                "permission": (
                    tool.permission.value
                ),
                "input_schema": (
                    tool.input_schema
                ),
            }
            for tool
            in self.definitions()
        ]

    def validate_request(
        self,
        request: ToolRequest,
    ) -> ToolDefinition:
        tool = self.get(
            request.tool_name
        )

        if (
            request.permission
            != tool.permission
        ):
            raise ToolPermissionError(
                "ToolRequest permission ile "
                "ToolDefinition permission eslesmiyor: "
                f"{request.tool_name}"
            )

        self._validate_arguments(
            tool,
            request.arguments,
        )

        return tool

    def _validate_arguments(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> None:
        schema = tool.input_schema

        required = schema.get(
            "required",
            [],
        )

        if not isinstance(
            required,
            list,
        ):
            raise ToolValidationError(
                f"{tool.name} required list olmali."
            )

        missing = [
            field
            for field in required
            if field not in arguments
        ]

        if missing:
            raise ToolValidationError(
                f"{tool.name} eksik arguman: "
                f"{missing}"
            )

        properties = schema.get(
            "properties",
            {},
        )

        if not isinstance(
            properties,
            dict,
        ):
            raise ToolValidationError(
                f"{tool.name} properties dict olmali."
            )

        allow_extra = schema.get(
            "additionalProperties",
            False,
        )

        if not allow_extra:
            unknown = [
                key
                for key in arguments
                if key not in properties
            ]

            if unknown:
                raise ToolValidationError(
                    f"{tool.name} bilinmeyen arguman: "
                    f"{unknown}"
                )

        for key, value in arguments.items():
            spec = properties.get(key)

            if not isinstance(
                spec,
                dict,
            ):
                continue

            expected_type = spec.get(
                "type"
            )

            if expected_type is None:
                continue

            if not _matches_json_type(
                value,
                expected_type,
            ):
                raise ToolValidationError(
                    f"{tool.name}.{key} tipi "
                    f"{expected_type} olmali."
                )

    def bind_handler(
        self,
        name: str,
        handler: ToolHandler,
    ) -> None:
        tool = self.get(name)

        self._tools[name] = ToolDefinition(
            name=tool.name,
            description=tool.description,
            permission=tool.permission,
            input_schema=tool.input_schema,
            handler=handler,
        )

    def execute(
        self,
        request: ToolRequest,
    ) -> Any:
        tool = self.validate_request(
            request
        )

        if tool.handler is None:
            raise ToolRegistryError(
                f"Tool handler bagli degil: {tool.name}"
            )

        return tool.handler(
            request.arguments,
            request.cwd,
        )


def _matches_json_type(
    value: Any,
    expected_type: str,
) -> bool:
    mapping: dict[
        str,
        tuple[type, ...],
    ] = {
        "string": (str,),
        "integer": (int,),
        "number": (
            int,
            float,
        ),
        "boolean": (bool,),
        "object": (dict,),
        "array": (
            list,
            tuple,
        ),
        "null": (
            type(None),
        ),
    }

    accepted = mapping.get(
        expected_type
    )

    if accepted is None:
        return True

    if (
        expected_type
        in {
            "integer",
            "number",
        }
        and isinstance(
            value,
            bool,
        )
    ):
        return False

    return isinstance(
        value,
        accepted,
    )


def build_contract_registry(
) -> ToolRegistry:
    # FAZ 1B: sadece sozlesme katalogu.
    return ToolRegistry(
        [
            ToolDefinition(
                name="list_files",
                description=(
                    "Proje kokundeki dosya ve klasorleri listele."
                ),
                permission=Permission.READ,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="find_files",
                description=(
                    "Proje icinde dosya adi veya glob deseni ile dosya ara."
                ),
                permission=Permission.READ,
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "pattern",
                    ],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="read_file",
                description=(
                    "Proje icindeki bir metin dosyasini oku."
                ),
                permission=Permission.READ,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "path",
                    ],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="file_exists",
                description=(
                    "Proje icinde belirtilen yol mevcut mu kontrol et."
                ),
                permission=Permission.READ,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "path",
                    ],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="write_file",
                description=(
                    "Proje icinde bir dosyanin tam icerigini yaz veya olustur."
                ),
                permission=Permission.WRITE,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                        },
                        "content": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "path",
                        "content",
                    ],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="run_process",
                description=(
                    "Bir programi shell kullanmadan argv listesi ile calistir."
                ),
                permission=Permission.EXECUTE,
                input_schema={
                    "type": "object",
                    "properties": {
                        "argv": {
                            "type": "array",
                        },
                        "timeout_seconds": {
                            "type": "integer",
                        },
                    },
                    "required": [
                        "argv",
                    ],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="git_diff",
                description=(
                    "Mevcut repository degisikliklerini diff olarak oku."
                ),
                permission=Permission.READ,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="run_tests",
                description=(
                    "Projenin testlerini kontrollu olarak calistir."
                ),
                permission=Permission.EXECUTE,
                input_schema={
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            ),
        ]
    )
