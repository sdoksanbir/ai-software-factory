from factory.model_patch_parser import (
    parse_model_patch_response,
)


def test_plain_json():
    result = parse_model_patch_response(
        """{
          "files": [
            {
              "path": "a.py",
              "content": "x = 1"
            }
          ],
          "explanation": "ok"
        }"""
    )

    assert len(result.files) == 1
    assert result.files[0].path == "a.py"


def test_markdown_json_fence():
    result = parse_model_patch_response(
        """```json
{
  "files": [
    {
      "path": "a.py",
      "content": "x = 1"
    }
  ],
  "explanation": "ok"
}
```"""
    )

    assert result.files[0].path == "a.py"


def test_prose_around_json():
    result = parse_model_patch_response(
        """Here is the result:

{
  "files": [
    {
      "path": "a.py",
      "content": "x = 1"
    }
  ]
}

Done."""
    )

    assert result.files[0].path == "a.py"


def test_single_file_object():
    result = parse_model_patch_response(
        """{
          "path": "a.py",
          "content": "x = 1"
        }"""
    )

    assert len(result.files) == 1
    assert result.files[0].path == "a.py"
    assert result.files[0].operation == "write"


def test_delete_operation_preserved():
    result = parse_model_patch_response(
        """{
          "files": [
            {
              "path": "old.py",
              "operation": "delete"
            }
          ],
          "explanation": "remove obsolete file"
        }"""
    )

    assert len(result.files) == 1
    assert result.files[0].path == "old.py"
    assert result.files[0].operation == "delete"
    assert result.files[0].content == ""
