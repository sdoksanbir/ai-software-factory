import { useEffect, useMemo, useRef, useState } from "react"
import type {
  ControlCenterStatus,
  Task,
} from "../../api"
import {
  browseProjectFolder,
  inspectProjectPath,
  openProject,
} from "../../api"
import { FactoryBear } from "../factory/FactoryBear"
import { OpsIcon } from "./opsIcons"
import "../factory/FactoryVisuals.css"
import "./ProjectsWorkspace.css"

type ProjectItem = {
  project_id: string
  name: string
  path: string
  created_at?: string | null
  updated_at?: string | null
}

type Props = {
  projects: ProjectItem[]
  tasks: Task[]
  selectedProjectId: string | null
  controlCenter: ControlCenterStatus | null
  newProjectName: string
  newProjectPath: string
  projectSubmitting: boolean
  projectCreateError: string | null
  projectSettingsName: string
  projectSettingsPath: string
  projectSettingsSaving: boolean
  projectDeleting: boolean
  onSelectProject: (projectId: string) => void
  onNewProjectNameChange: (value: string) => void
  onNewProjectPathChange: (value: string) => void
  onCreateProject: (payload: {
    name: string
    path: string
    initGit?: boolean
  }) => void
  onCreateNewProject: (payload: {
    name: string
    parentPath: string
    initGit?: boolean
    createReadme?: boolean
    createGitignore?: boolean
  }) => void
  onProjectSettingsNameChange: (value: string) => void
  onProjectSettingsPathChange: (value: string) => void
  onSaveProjectSettings: (event: React.FormEvent<HTMLFormElement>) => void
  onDeleteProject: (projectId: string) => Promise<void>
}

type CharacterKind =
  | "developer"
  | "student"
  | "analyst"
  | "builder"
  | "writer"
  | "ops"

const CHARACTER_META: Record<
  CharacterKind,
  { label: string; variant: number; tags: string[]; blurb: string }
> = {
  developer: {
    label: "Geliştirici",
    variant: 2,
    tags: ["Üretkenlik", "Yapay Zeka", "Platform"],
    blurb:
      "AI destekli yazılım üretim hattı ve operasyon merkezi.",
  },
  student: {
    label: "Eğitim",
    variant: 1,
    tags: ["Eğitim", "Web Uygulaması", "AI"],
    blurb:
      "Öğrenme ve değerlendirme odaklı web uygulaması.",
  },
  analyst: {
    label: "Analist",
    variant: 1,
    tags: ["Analiz", "Veri", "Rapor"],
    blurb: "Keşif, analiz ve karar destek projesi.",
  },
  builder: {
    label: "Kurucu",
    variant: 5,
    tags: ["Altyapı", "Entegrasyon", "DevOps"],
    blurb: "Dağıtım ve birleştirme odaklı sistem projesi.",
  },
  writer: {
    label: "Yazar",
    variant: 3,
    tags: ["İçerik", "Dokümantasyon", "CMS"],
    blurb: "İçerik üretimi ve dokümantasyon çalışma alanı.",
  },
  ops: {
    label: "Operasyon",
    variant: 4,
    tags: ["İzleme", "Kalite", "Operasyon"],
    blurb: "Doğrulama ve operasyon takibi için proje.",
  },
}

function hashText(value: string) {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0
  }
  return Math.abs(hash)
}

function resolveCharacter(project: ProjectItem): CharacterKind {
  const text = `${project.name} ${project.path}`.toLowerCase()
  if (/edu|öğr|okul|school|course|test|exam|learn/.test(text)) {
    return "student"
  }
  if (/analy|data|metric|report|insight/.test(text)) return "analyst"
  if (/ops|monitor|health|qa|verify/.test(text)) return "ops"
  if (/docs|content|cms|blog|write/.test(text)) return "writer"
  if (/deploy|infra|docker|ci|merge|factory/.test(text)) return "builder"
  if (/ai|software|code|dev|app|platform/.test(text)) return "developer"
  const kinds = Object.keys(CHARACTER_META) as CharacterKind[]
  return kinds[hashText(project.project_id) % kinds.length]
}

function relativeTime(value: string | null | undefined) {
  if (!value) return "—"
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return "—"
  const mins = Math.max(0, Math.round((Date.now() - time) / 60000))
  if (mins < 1) return "şimdi"
  if (mins < 60) return `${mins} dk önce`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} saat önce`
  return `${Math.floor(hours / 24)} gün önce`
}

function shortPath(path: string) {
  const normalized = path.replace(/\\/g, "/")
  const parts = normalized.split("/").filter(Boolean)
  if (parts.length <= 2) return path
  return `${parts.slice(-2).join("/")}`
}

function projectCreateErrorTr(message: string) {
  const map: Record<string, string> = {
    "Project path is not a Git repository":
      "Seçilen klasör bir Git deposu değil. Klasörün içinde .git bulunmalı.",
    "Project directory does not exist":
      "Seçilen klasör bulunamadı.",
    "Project path is already registered":
      "Bu proje yolu zaten kayıtlı.",
    "Project not found":
      "Proje artık mevcut değil.",
  }
  return map[message] ?? message
}

const RESERVED_WINDOWS_NAMES = new Set([
  "CON",
  "PRN",
  "AUX",
  "NUL",
  ...Array.from({ length: 9 }, (_, i) => `COM${i + 1}`),
  ...Array.from({ length: 9 }, (_, i) => `LPT${i + 1}`),
])

function hasInvalidProjectNameChar(value: string): boolean {
  for (const ch of value) {
    const code = ch.charCodeAt(0)
    if (code < 32) return true
    if ('<>:"/\\|?*'.includes(ch)) return true
  }
  return false
}

/** Mirrors factory.project_creator.validate_project_name */
function validateProjectName(name: string): string {
  const clean = name.trim()
  if (!clean) {
    throw new Error("Proje adı boş olamaz.")
  }
  if (clean === "." || clean === "..") {
    throw new Error("Geçersiz proje adı.")
  }
  if (hasInvalidProjectNameChar(clean)) {
    throw new Error(
      'Proje adı şu karakterleri içeremez: < > : " / \\ | ? *',
    )
  }
  if (clean.endsWith(" ") || clean.endsWith(".")) {
    throw new Error("Proje adı boşluk veya nokta ile bitemez.")
  }
  const stem = clean.split(".", 1)[0].toUpperCase()
  if (RESERVED_WINDOWS_NAMES.has(stem)) {
    throw new Error(
      `Bu proje adı Windows tarafından ayrılmıştır: ${clean}`,
    )
  }
  return clean
}

/** Mirrors factory.project_creator.project_name_slug */
function projectNameSlug(name: string): string {
  const clean = validateProjectName(name)
  let slug = clean.replace(/\s+/g, "-").replace(/^[.-]+|[.-]+$/g, "")
  if (!slug) {
    throw new Error("Geçersiz proje adı.")
  }
  const stem = slug.split(".", 1)[0].toUpperCase()
  if (RESERVED_WINDOWS_NAMES.has(stem)) {
    throw new Error(
      `Bu proje adı Windows tarafından ayrılmıştır: ${slug}`,
    )
  }
  if (hasInvalidProjectNameChar(slug)) {
    throw new Error(
      'Proje adı şu karakterleri içeremez: < > : " / \\ | ? *',
    )
  }
  return slug
}

function tryProjectNameSlug(name: string): {
  slug: string | null
  error: string | null
} {
  try {
    return { slug: projectNameSlug(name), error: null }
  } catch (err) {
    return {
      slug: null,
      error: err instanceof Error ? err.message : "Geçersiz proje adı.",
    }
  }
}

function joinPath(parent: string, child: string) {
  const normalizedParent = parent.replace(/[\\/]+$/, "")
  const sep = parent.includes("\\") ? "\\" : "/"
  return `${normalizedParent}${sep}${child}`
}

function folderBasename(path: string) {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean)
  return parts[parts.length - 1] ?? ""
}

function pathsMatch(a: string, b: string) {
  return (
    a.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase() ===
    b.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase()
  )
}

function taskStateLabel(state: string) {
  const map: Record<string, string> = {
    queued: "Sırada",
    running: "Çalışıyor",
    ready_for_approval: "Onay bekliyor",
    approved: "Tamamlandı",
    completed: "Tamamlandı",
    rejected: "Reddedildi",
    failed: "Başarısız",
  }
  return map[state] ?? state
}

function MiniIcon({
  name,
}: {
  name:
    | "folder"
    | "play"
    | "check"
    | "clock"
    | "git"
    | "branch"
    | "tasks"
    | "search"
    | "arrow"
}) {
  const p = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  }
  switch (name) {
    case "folder":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...p} d="M3 7h6l2 2h10v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          <path {...p} d="M3 7V5a2 2 0 0 1 2-2h4l2 2" />
        </svg>
      )
    case "play":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle {...p} cx="12" cy="12" r="9" />
          <path {...p} d="M10 8l7 4-7 4z" />
        </svg>
      )
    case "check":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <rect {...p} x="4" y="4" width="16" height="16" rx="3" />
          <path {...p} d="M8 12l3 3 5-6" />
        </svg>
      )
    case "clock":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle {...p} cx="12" cy="12" r="9" />
          <path {...p} d="M12 7v5l3 2" />
        </svg>
      )
    case "git":
      return (
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <circle {...p} cx="6" cy="6" r="2.2" />
          <circle {...p} cx="18" cy="12" r="2.2" />
          <circle {...p} cx="6" cy="18" r="2.2" />
          <path {...p} d="M6 8v8M8 6h6a4 4 0 0 1 4 4" />
        </svg>
      )
    case "branch":
      return (
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <circle {...p} cx="6" cy="6" r="2.2" />
          <circle {...p} cx="18" cy="6" r="2.2" />
          <circle {...p} cx="6" cy="18" r="2.2" />
          <path {...p} d="M6 8v8M8 6h4a4 4 0 0 1 4 4v0" />
        </svg>
      )
    case "tasks":
      return (
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <path {...p} d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />
        </svg>
      )
    case "search":
      return (
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <circle {...p} cx="11" cy="11" r="6.5" />
          <path {...p} d="M16 16l4 4" />
        </svg>
      )
    case "arrow":
      return (
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <path {...p} d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      )
  }
}

function NeonBadge({ kind }: { kind: CharacterKind }) {
  if (kind === "student") {
    return (
      <svg className="project-neon-badge" viewBox="0 0 64 64" aria-hidden="true">
        <rect x="14" y="18" width="36" height="28" rx="4" fill="none" stroke="#5bb8ff" strokeWidth="2.4" />
        <path d="M20 26h24M20 32h18M20 38h12" stroke="#5bb8ff" strokeWidth="2" strokeLinecap="round" />
        <circle cx="48" cy="44" r="8" fill="#0b1e33" stroke="#5bb8ff" strokeWidth="2" />
        <text x="48" y="48" textAnchor="middle" fill="#5bb8ff" fontSize="11" fontWeight="800">
          T
        </text>
      </svg>
    )
  }
  return (
    <svg className="project-neon-badge" viewBox="0 0 64 64" aria-hidden="true">
      <path
        d="M12 40V28l10-6 10 6v12M22 22v-6l8-4 8 4v6"
        fill="none"
        stroke="#ffb24a"
        strokeWidth="2.4"
        strokeLinejoin="round"
      />
      <path d="M18 40h28v6H18z" fill="none" stroke="#ffb24a" strokeWidth="2.2" />
      <circle cx="48" cy="18" r="7" fill="#0b1e33" stroke="#ffb24a" strokeWidth="2" />
      <path d="M45 18h6M48 15v6" stroke="#ffb24a" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function ProjectScene({
  kind,
  active,
}: {
  kind: CharacterKind
  active: boolean
}) {
  const meta = CHARACTER_META[kind]
  const student = kind === "student"

  return (
    <div className={`project-scene kind-${kind}`}>
      <div className="project-scene-wash" />
      <NeonBadge kind={kind} />

      <div className={`project-scene-bear ${student ? "is-student" : ""}`}>
        <FactoryBear
          variant={meta.variant}
          active={active}
          mood={active ? "working" : student ? "thinking" : "idle"}
          facing="toward"
          workPapers={active && !student}
        />
        {student && (
          <svg
            className="project-grad-cap"
            viewBox="0 0 90 40"
            aria-hidden="true"
          >
            <path d="M8 18 L45 6 L82 18 L45 30 Z" fill="#1a2b44" stroke="#8ec7ff" strokeWidth="2" />
            <path d="M45 30 v8" stroke="#8ec7ff" strokeWidth="2" />
            <circle cx="45" cy="38" r="2.5" fill="#ffd27a" />
            <path d="M68 18 v10" stroke="#ffd27a" strokeWidth="2" />
            <circle cx="68" cy="30" r="2.2" fill="#ffd27a" />
          </svg>
        )}
      </div>

      {student ? (
        <>
          <div className="project-prop book-stack left" />
          <div className="project-prop book-stack right" />
          <div className="project-prop open-book" />
        </>
      ) : (
        <>
          <div className="project-prop desk" />
          <div className="project-prop laptop" />
          <div className="project-prop plant" />
        </>
      )}
    </div>
  )
}

function HealthBadge({
  score,
  label,
  tone,
}: {
  score: number
  label: string
  tone: string
}) {
  return (
    <div className={`project-health tone-${tone}`}>
      <strong>{label}</strong>
      <small>%{score}</small>
    </div>
  )
}

export function ProjectsWorkspace({
  projects,
  tasks,
  selectedProjectId,
  controlCenter,
  newProjectName: _newProjectName,
  newProjectPath: _newProjectPath,
  projectSubmitting,
  projectCreateError,
  projectSettingsName,
  projectSettingsPath,
  projectSettingsSaving,
  projectDeleting,
  onSelectProject,
  onNewProjectNameChange: _onNewProjectNameChange,
  onNewProjectPathChange: _onNewProjectPathChange,
  onCreateProject,
  onCreateNewProject,
  onProjectSettingsNameChange,
  onProjectSettingsPathChange,
  onSaveProjectSettings,
  onDeleteProject,
}: Props) {
  const [query, setQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [sortBy, setSortBy] = useState("name")
  const [showComposer, setShowComposer] = useState(false)
  const [createMode, setCreateMode] = useState<"new" | "existing">("new")
  const [viewMode, setViewMode] = useState<"list" | "details">("list")
  const [openingId, setOpeningId] = useState<string | null>(null)
  const [createAttempted, setCreateAttempted] = useState(false)
  const [browsingFolder, setBrowsingFolder] = useState(false)
  const [localValidationError, setLocalValidationError] = useState<
    string | null
  >(null)
  // NEW mode owned state
  const [newProjectNameLocal, setNewProjectNameLocal] = useState("")
  const [newProjectParentPath, setNewProjectParentPath] = useState("")
  const [initGit, setInitGit] = useState(true)
  const [createReadme, setCreateReadme] = useState(true)
  const [createGitignore, setCreateGitignore] = useState(true)
  // EXISTING mode owned state
  const [existingProjectRootPath, setExistingProjectRootPath] = useState("")
  const [existingHasGit, setExistingHasGit] = useState<boolean | null>(
    null,
  )
  const [existingCharacteristics, setExistingCharacteristics] = useState<
    string[]
  >([])
  const [inspectingPath, setInspectingPath] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<ProjectItem | null>(
    null,
  )
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const projectCountAtSubmit = useRef(projects.length)

  const selected =
    projects.find((p) => p.project_id === selectedProjectId) ??
    projects[0] ??
    null

  const pendingTasks = tasks.filter(
    (task) =>
      task.state === "queued" ||
      task.state === "running" ||
      task.state === "ready_for_approval",
  ).length

  const pendingPct = Math.min(
    100,
    Math.round((pendingTasks / Math.max(tasks.length, 1)) * 100),
  )

  const lastUpdate = useMemo(() => {
    const times = [
      ...projects.map((p) => p.updated_at ?? p.created_at),
      ...tasks.map((t) => t.started_at),
    ].filter(Boolean) as string[]
    if (times.length === 0) return null
    return times
      .slice()
      .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0]
  }, [projects, tasks])

  const cards = useMemo(() => {
    const filtered = projects.filter((project) => {
      const hay = `${project.name} ${project.path}`.toLowerCase()
      if (query && !hay.includes(query.toLowerCase())) return false
      if (
        statusFilter === "active" &&
        project.project_id !== selectedProjectId
      ) {
        return false
      }
      return true
    })

    return filtered
      .slice()
      .sort((a, b) => {
        if (sortBy === "tasks") {
          const aCount = tasks.filter((t) => t.project_id === a.project_id)
            .length
          const bCount = tasks.filter((t) => t.project_id === b.project_id)
            .length
          return bCount - aCount
        }
        if (sortBy === "updated") {
          return (
            new Date(b.updated_at ?? b.created_at ?? 0).getTime() -
            new Date(a.updated_at ?? a.created_at ?? 0).getTime()
          )
        }
        return a.name.localeCompare(b.name, "tr")
      })
      .map((project) => {
        const kind = resolveCharacter(project)
        const meta = CHARACTER_META[kind]
        const projectTasks = tasks.filter(
          (task) => task.project_id === project.project_id,
        )
        const running = projectTasks.some((task) => task.state === "running")
        const failed = projectTasks.some((task) => task.state === "failed")
        const health = failed
          ? "attention"
          : running
            ? "building"
            : "healthy"
        return {
          project,
          kind,
          meta,
          projectTasks,
          running,
          health,
          healthLabel:
            health === "healthy"
              ? "Sağlıklı"
              : health === "building"
                ? "Geliştiriliyor"
                : "Dikkat",
          healthScore:
            health === "healthy" ? 92 : health === "building" ? 68 : 42,
        }
      })
  }, [projects, query, selectedProjectId, sortBy, statusFilter, tasks])

  const selectedTasks = selected
    ? tasks
        .filter((task) => task.project_id === selected.project_id)
        .slice()
        .reverse()
        .slice(0, 5)
    : []

  const detailTasks = useMemo(() => {
    if (!selected) return []
    return tasks
      .filter((task) => task.project_id === selected.project_id)
      .slice()
      .sort((a, b) => {
        const aTime = new Date(a.started_at ?? 0).getTime()
        const bTime = new Date(b.started_at ?? 0).getTime()
        return bTime - aTime
      })
      .slice(0, 6)
  }, [selected, tasks])

  const detailStats = useMemo(() => {
    if (!selected) {
      return {
        total: 0,
        working: 0,
        completed: 0,
        failed: 0,
        approval: 0,
      }
    }
    const projectTasks = tasks.filter(
      (task) => task.project_id === selected.project_id,
    )
    return {
      total: projectTasks.length,
      working: projectTasks.filter(
        (task) => task.state === "queued" || task.state === "running",
      ).length,
      completed: projectTasks.filter(
        (task) =>
          task.state === "completed" || task.state === "approved",
      ).length,
      failed: projectTasks.filter(
        (task) =>
          task.state === "failed" || task.state === "rejected",
      ).length,
      approval: projectTasks.filter(
        (task) => task.state === "ready_for_approval",
      ).length,
    }
  }, [selected, tasks])

  const selectedKind = selected ? resolveCharacter(selected) : "developer"
  const selectedMeta = CHARACTER_META[selectedKind]
  const selectedHealth = cards.find(
    (c) => c.project.project_id === selected?.project_id,
  )

  const detailLastActivity =
    detailTasks[0]?.started_at ??
    selected?.updated_at ??
    selected?.created_at ??
    null

  const gitStatusLabel = !controlCenter?.git.available
    ? "—"
    : controlCenter.git.clean === true
      ? "Temiz"
      : controlCenter.git.clean === false
        ? "Değişiklik var"
        : "—"

  useEffect(() => {
    if (viewMode === "details" && !selected) {
      setViewMode("list")
    }
  }, [selected, viewMode])

  async function handleOpen(projectId: string) {
    setOpeningId(projectId)
    try {
      onSelectProject(projectId)
      await openProject(projectId)
    } finally {
      setOpeningId(null)
    }
  }

  function requestDelete(project: ProjectItem) {
    setDeleteError(null)
    setPendingDelete(project)
  }

  function cancelDelete() {
    if (projectDeleting) {
      return
    }
    setPendingDelete(null)
    setDeleteError(null)
  }

  async function confirmDelete() {
    if (!pendingDelete || projectDeleting) {
      return
    }

    setDeleteError(null)

    try {
      await onDeleteProject(pendingDelete.project_id)
      setPendingDelete(null)
      setViewMode("list")
    } catch (err) {
      setDeleteError(
        projectCreateErrorTr(
          err instanceof Error
            ? err.message
            : "Proje kaldırılamadı.",
        ),
      )
    }
  }

  function resetExistingInspect() {
    setExistingHasGit(null)
    setExistingCharacteristics([])
  }

  function clearComposerLocalState() {
    setNewProjectNameLocal("")
    setNewProjectParentPath("")
    setExistingProjectRootPath("")
    setInitGit(true)
    setCreateReadme(true)
    setCreateGitignore(true)
    resetExistingInspect()
    setLocalValidationError(null)
    setCreateAttempted(false)
  }

  async function inspectExistingRoot(path: string) {
    const clean = path.trim()
    if (!clean) {
      resetExistingInspect()
      return
    }

    setInspectingPath(true)
    try {
      const info = await inspectProjectPath(clean)
      setExistingHasGit(Boolean(info.has_git))
      setExistingCharacteristics(info.characteristics ?? [])
    } catch {
      resetExistingInspect()
    } finally {
      setInspectingPath(false)
    }
  }

  async function handleBrowseFolder() {
    setBrowsingFolder(true)
    setLocalValidationError(null)
    try {
      const result = await browseProjectFolder({
        title:
          createMode === "new"
            ? "Ebeveyn klasör seç"
            : "Proje kök klasörü seç",
      })
      const selectedPath = result.path?.trim()
      if (!selectedPath) {
        return
      }

      if (createMode === "existing") {
        setExistingProjectRootPath(selectedPath)
        if (typeof result.has_git === "boolean") {
          setExistingHasGit(result.has_git)
          setExistingCharacteristics(result.characteristics ?? [])
        } else {
          await inspectExistingRoot(selectedPath)
        }
        return
      }

      setNewProjectParentPath(selectedPath)
    } catch {
      // Kullanıcı iptal ettiyse veya diyalog açılamadıysa sessiz geç.
    } finally {
      setBrowsingFolder(false)
    }
  }

  const nameValidation = useMemo(
    () => tryProjectNameSlug(newProjectNameLocal),
    [newProjectNameLocal],
  )

  const plannedTargetPath = useMemo(() => {
    if (createMode !== "new") return ""
    const parent = newProjectParentPath.trim()
    if (!parent || !nameValidation.slug) return ""
    return joinPath(parent, nameValidation.slug)
  }, [createMode, newProjectParentPath, nameValidation.slug])

  const registeredPathConflict = useMemo(() => {
    const candidate =
      createMode === "new"
        ? plannedTargetPath
        : existingProjectRootPath.trim()
    if (!candidate) return false
    return projects.some((project) =>
      pathsMatch(project.path, candidate),
    )
  }, [
    createMode,
    plannedTargetPath,
    existingProjectRootPath,
    projects,
  ])

  function handleCreateProjectSubmit(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (createMode === "existing") {
      if (existingHasGit !== true) {
        setCreateAttempted(true)
        setLocalValidationError(
          existingHasGit === false
            ? "Git bulunamadı. 'Git Oluştur ve Ekle' düğmesini kullanın."
            : "Önce geçerli bir proje kök klasörü seçin.",
        )
        return
      }
      handleAddExisting(false)
      return
    }

    projectCountAtSubmit.current = projects.length
    setCreateAttempted(true)
    setLocalValidationError(null)

    const cleanName = newProjectNameLocal.trim()
    const cleanParent = newProjectParentPath.trim()

    if (!cleanName) {
      setLocalValidationError("Proje adı zorunludur.")
      return
    }
    if (nameValidation.error) {
      setLocalValidationError(nameValidation.error)
      return
    }
    if (!cleanParent) {
      setLocalValidationError("Ebeveyn klasör zorunludur.")
      return
    }
    if (!nameValidation.slug) {
      setLocalValidationError("Geçerli bir proje adı girin.")
      return
    }
    if (registeredPathConflict) {
      setLocalValidationError(
        "Bu proje yolu Factory'de zaten kayıtlı.",
      )
      return
    }

    onCreateNewProject({
      name: cleanName,
      parentPath: cleanParent,
      initGit,
      createReadme,
      createGitignore,
    })
  }

  function handleAddExisting(initGitOnAdd: boolean) {
    projectCountAtSubmit.current = projects.length
    setCreateAttempted(true)
    setLocalValidationError(null)

    const cleanPath = existingProjectRootPath.trim()
    if (!cleanPath) {
      setLocalValidationError("Proje kök klasörü zorunludur.")
      return
    }
    if (registeredPathConflict) {
      setLocalValidationError(
        "Bu proje yolu Factory'de zaten kayıtlı.",
      )
      return
    }

    const derivedName = folderBasename(cleanPath)
    if (!derivedName) {
      setLocalValidationError("Proje adı türetilemedi.")
      return
    }

    onCreateProject({
      name: derivedName,
      path: cleanPath,
      initGit: initGitOnAdd,
    })
  }

  useEffect(() => {
    if (
      createAttempted &&
      projects.length > projectCountAtSubmit.current
    ) {
      setShowComposer(false)
      clearComposerLocalState()
    }
  }, [createAttempted, projects.length])

  useEffect(() => {
    if (createMode !== "existing") {
      resetExistingInspect()
      return
    }

    const path = existingProjectRootPath.trim()
    if (!path) {
      resetExistingInspect()
      return
    }

    const timer = window.setTimeout(() => {
      void inspectExistingRoot(path)
    }, 350)

    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createMode, existingProjectRootPath])

  useEffect(() => {
    if (!showComposer) {
      setCreateAttempted(false)
      setLocalValidationError(null)
    }
  }, [showComposer])

  return (
    <div
      className={`projects-workspace${
        viewMode === "details" ? " details-mode" : ""
      }`}
    >
      {pendingDelete ? (
        <div
          className="projects-delete-overlay"
          role="presentation"
          onClick={cancelDelete}
        >
          <div
            className="projects-delete-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="projects-delete-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 id="projects-delete-title">Projeyi Kaldır</h3>
            <p className="projects-delete-name">
              <strong>{pendingDelete.name}</strong>
            </p>
            <p>
              Bu işlem projeyi yalnızca AI Software Factory listesinden
              kaldırır. Bilgisayarınızdaki proje dosyaları silinmez.
            </p>
            {deleteError ? (
              <p className="projects-delete-error" role="alert">
                {deleteError}
              </p>
            ) : null}
            <div className="projects-delete-actions">
              <button
                type="button"
                className="projects-delete-cancel"
                onClick={cancelDelete}
                disabled={projectDeleting}
              >
                İptal
              </button>
              <button
                type="button"
                className="projects-delete-confirm"
                onClick={() => {
                  void confirmDelete()
                }}
                disabled={projectDeleting}
              >
                {projectDeleting ? "Kaldırılıyor..." : "Projeyi Kaldır"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {viewMode === "details" && selected ? (
        <div className="projects-details">
          <header className="projects-details-hero">
            <div className="projects-details-hero-main">
              <button
                type="button"
                className="projects-details-back"
                onClick={() => setViewMode("list")}
              >
                ← Projelere Dön
              </button>

              <div className="projects-details-title-row">
                <div className="projects-details-avatar">
                  <FactoryBear
                    variant={selectedMeta.variant}
                    mood="idle"
                    facing="toward"
                    portrait
                  />
                </div>
                <div className="projects-details-copy">
                  <h2>{selected.name}</h2>
                  <em>{selectedMeta.label}</em>
                  <p>{selectedMeta.blurb}</p>
                </div>
              </div>
            </div>

            <div className="projects-details-hero-actions">
              <span
                className={`projects-details-health tone-${
                  selectedHealth?.health ?? "healthy"
                }`}
              >
                <i />
                {selectedHealth?.healthLabel ?? "Sağlıklı"}
              </span>
              <button
                type="button"
                className="project-open"
                onClick={() => {
                  void handleOpen(selected.project_id)
                }}
                disabled={openingId === selected.project_id}
              >
                {openingId === selected.project_id
                  ? "Açılıyor..."
                  : "Projeyi Aç"}
                <MiniIcon name="arrow" />
              </button>
              <button
                type="button"
                className="project-remove"
                onClick={() => requestDelete(selected)}
                disabled={projectDeleting}
              >
                Projeyi Kaldır
              </button>
            </div>
          </header>

          <div className="projects-details-kpi-row">
            <article className="projects-kpi tone-blue">
              <div className="projects-kpi-text">
                <span>Toplam Görev</span>
                <strong>{detailStats.total}</strong>
              </div>
              <div className="projects-kpi-icon">
                <MiniIcon name="tasks" />
              </div>
            </article>
            <article className="projects-kpi tone-purple">
              <div className="projects-kpi-text">
                <span>Çalışan</span>
                <strong>{detailStats.working}</strong>
                <small>Onay bekleyen: {detailStats.approval}</small>
              </div>
              <div className="projects-kpi-icon">
                <MiniIcon name="play" />
              </div>
            </article>
            <article className="projects-kpi tone-green">
              <div className="projects-kpi-text">
                <span>Tamamlanan</span>
                <strong>{detailStats.completed}</strong>
              </div>
              <div className="projects-kpi-icon">
                <MiniIcon name="check" />
              </div>
            </article>
            <article className="projects-kpi tone-orange">
              <div className="projects-kpi-text">
                <span>Başarısız</span>
                <strong>{detailStats.failed}</strong>
              </div>
              <div className="projects-kpi-icon">
                <MiniIcon name="clock" />
              </div>
            </article>
          </div>

          <div className="projects-details-grid">
            <section className="projects-details-card">
              <div className="projects-side-head">
                <span>ÖZET</span>
                <h3>Proje Özeti</h3>
              </div>
              <dl className="projects-side-facts">
                <div>
                  <dt>Proje türü</dt>
                  <dd>{selectedMeta.label}</dd>
                </div>
                <div>
                  <dt>Durum</dt>
                  <dd>
                    <span className="projects-pill">
                      {selectedHealth?.healthLabel ?? "Sağlıklı"}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Oluşturulma</dt>
                  <dd>{relativeTime(selected.created_at)}</dd>
                </div>
                <div>
                  <dt>Son güncelleme</dt>
                  <dd>{relativeTime(selected.updated_at)}</dd>
                </div>
                <div>
                  <dt>Son aktivite</dt>
                  <dd>{relativeTime(detailLastActivity)}</dd>
                </div>
              </dl>
            </section>

            <section className="projects-details-card">
              <div className="projects-side-head">
                <span>REPOSITORY</span>
                <h3>Depo Bilgisi</h3>
              </div>
              <dl className="projects-side-facts">
                <div>
                  <dt>Repo yolu</dt>
                  <dd className="projects-path-ellipsis" title={selected.path}>
                    {selected.path}
                  </dd>
                </div>
                <div>
                  <dt>Aktif dal</dt>
                  <dd>{controlCenter?.git.branch ?? "—"}</dd>
                </div>
                <div>
                  <dt>Git durumu</dt>
                  <dd>{gitStatusLabel}</dd>
                </div>
                <div>
                  <dt>Proje ID</dt>
                  <dd>{selected.project_id}</dd>
                </div>
              </dl>
            </section>

            <section className="projects-details-card projects-details-tasks">
              <div className="projects-side-head">
                <span>AKTİVİTE</span>
                <h3>Son Görevler</h3>
              </div>
              {detailTasks.length === 0 ? (
                <p className="projects-side-empty">
                  Bu projede henüz görev yok.
                </p>
              ) : (
                <ul className="projects-details-task-list">
                  {detailTasks.map((task) => (
                    <li
                      key={task.task_id}
                      className={`tone-${task.state}`}
                    >
                      <div className="projects-details-task-top">
                        <strong>{task.task_id}</strong>
                        <em>{taskStateLabel(task.state)}</em>
                      </div>
                      <p>
                        {(task.prompt || "—").slice(0, 90)}
                        {(task.prompt || "").length > 90 ? "…" : ""}
                      </p>
                      <div className="projects-details-task-meta">
                        {task.model ? <span>{task.model}</span> : null}
                        <span>{relativeTime(task.started_at)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="projects-details-card">
              <div className="projects-side-head">
                <span>AYARLAR</span>
                <h3>Proje Ayarları</h3>
              </div>
              <form
                className="projects-settings-form"
                onSubmit={onSaveProjectSettings}
              >
                <label>
                  <span>Proje adı</span>
                  <input
                    value={projectSettingsName}
                    onChange={(event) =>
                      onProjectSettingsNameChange(event.target.value)
                    }
                  />
                </label>
                <label>
                  <span>Proje yolu</span>
                  <input
                    value={projectSettingsPath}
                    onChange={(event) =>
                      onProjectSettingsPathChange(event.target.value)
                    }
                  />
                </label>
                <button type="submit" disabled={projectSettingsSaving}>
                  {projectSettingsSaving
                    ? "Kaydediliyor..."
                    : "Değişiklikleri Kaydet"}
                </button>
              </form>
              <div className="projects-danger-zone">
                <p>
                  Factory kaydını kaldırır; diskteki dosyalar korunur.
                </p>
                <button
                  type="button"
                  className="project-remove"
                  onClick={() => requestDelete(selected)}
                  disabled={projectDeleting}
                >
                  Projeyi Kaldır
                </button>
              </div>
            </section>
          </div>
        </div>
      ) : (
        <>
      <div className="projects-main">
        <div className="projects-kpi-row">
          <article className="projects-kpi tone-blue">
            <div className="projects-kpi-text">
              <span>Toplam Proje</span>
              <strong>{projects.length}</strong>
              <small className="up">
                +{Math.max(0, projects.length - 1) || (projects.length ? 1 : 0)}
              </small>
            </div>
            <div className="projects-kpi-icon">
              <MiniIcon name="folder" />
            </div>
          </article>

          <article className="projects-kpi tone-green">
            <div className="projects-kpi-text">
              <span>Aktif Proje</span>
              <strong>{projects.length}</strong>
              <div className="projects-kpi-bar">
                <i style={{ width: "100%" }} />
              </div>
              <small>%100</small>
            </div>
            <div className="projects-kpi-icon">
              <MiniIcon name="play" />
            </div>
          </article>

          <article className="projects-kpi tone-purple">
            <div className="projects-kpi-text">
              <span>Bekleyen Görev</span>
              <strong>{pendingTasks}</strong>
              <div className="projects-kpi-bar">
                <i style={{ width: `${pendingPct}%` }} />
              </div>
              <small>%{pendingPct}</small>
            </div>
            <div className="projects-kpi-icon">
              <MiniIcon name="check" />
            </div>
          </article>

          <article className="projects-kpi tone-orange">
            <div className="projects-kpi-text">
              <span>Son Güncelleme</span>
              <strong className="projects-kpi-time">
                {relativeTime(lastUpdate)}
              </strong>
            </div>
            <div className="projects-kpi-icon">
              <MiniIcon name="clock" />
            </div>
          </article>
        </div>

        <div className="projects-toolbar">
          <label className="projects-search">
            <MiniIcon name="search" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Proje ara..."
            />
          </label>
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="all">Tümü</option>
            <option value="active">Aktif</option>
          </select>
          <select
            value="status"
            onChange={() => undefined}
            aria-label="Durum"
          >
            <option value="status">Durum</option>
            <option value="healthy">Sağlıklı</option>
            <option value="building">Geliştiriliyor</option>
          </select>
          <select
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value)}
          >
            <option value="name">Sıralama</option>
            <option value="updated">Son güncelleme</option>
            <option value="tasks">Görev sayısı</option>
          </select>
        </div>

        {showComposer && (
          <form
            className="projects-composer projects-composer-v2"
            onSubmit={handleCreateProjectSubmit}
          >
            <div className="projects-create-mode" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={createMode === "new"}
                className={createMode === "new" ? "active" : ""}
                onClick={() => {
                  setCreateMode("new")
                  setLocalValidationError(null)
                  setCreateAttempted(false)
                  resetExistingInspect()
                }}
              >
                Yeni Proje Oluştur
              </button>

              <button
                type="button"
                role="tab"
                aria-selected={createMode === "existing"}
                className={createMode === "existing" ? "active" : ""}
                onClick={() => {
                  setCreateMode("existing")
                  setLocalValidationError(null)
                  setCreateAttempted(false)
                }}
              >
                Mevcut Proje Ekle
              </button>
            </div>

            {createMode === "new" ? (
              <div className="projects-composer-panel">
                <label>
                  <span>Proje adı</span>
                  <input
                    value={newProjectNameLocal}
                    onChange={(event) =>
                      setNewProjectNameLocal(event.target.value)
                    }
                    placeholder="Örn: my-app"
                    required
                  />
                </label>
                {newProjectNameLocal.trim() && nameValidation.error ? (
                  <div className="projects-composer-error" role="alert">
                    <strong>Geçersiz proje adı</strong>
                    <span>{nameValidation.error}</span>
                  </div>
                ) : null}

                <label className="projects-composer-path-field">
                  <span>Ebeveyn klasör</span>
                  <div className="projects-path-picker">
                    <input
                      value={newProjectParentPath}
                      onChange={(event) =>
                        setNewProjectParentPath(event.target.value)
                      }
                      placeholder="D:\AI-Projects"
                      required
                    />
                    <button
                      type="button"
                      className="projects-browse-btn"
                      onClick={() => void handleBrowseFolder()}
                      disabled={browsingFolder}
                    >
                      {browsingFolder
                        ? "Açılıyor..."
                        : "Ebeveyn klasör seç"}
                    </button>
                  </div>
                </label>

                <div className="projects-composer-preview" aria-live="polite">
                  <span>Oluşturulacak proje yolu</span>
                  <strong>
                    {plannedTargetPath ||
                      (nameValidation.error
                        ? "Geçerli bir proje adı girildiğinde önizleme görünür"
                        : "Proje adı ve ebeveyn klasör girildiğinde önizleme görünür")}
                  </strong>
                </div>

                <p className="projects-composer-help">
                  Seçtiğiniz ebeveyn klasör içinde yeni bir proje klasörü
                  oluşturulur. Git deposu yeni oluşturulan klasörde
                  başlatılır.
                </p>

                <div className="projects-composer-checks">
                  <label className="projects-check">
                    <input
                      type="checkbox"
                      checked={initGit}
                      onChange={(event) => setInitGit(event.target.checked)}
                    />
                    <span>Git deposu oluştur</span>
                  </label>
                  <label className="projects-check">
                    <input
                      type="checkbox"
                      checked={createReadme}
                      onChange={(event) =>
                        setCreateReadme(event.target.checked)
                      }
                    />
                    <span>README.md oluştur</span>
                  </label>
                  <label className="projects-check">
                    <input
                      type="checkbox"
                      checked={createGitignore}
                      onChange={(event) =>
                        setCreateGitignore(event.target.checked)
                      }
                    />
                    <span>.gitignore oluştur</span>
                  </label>
                </div>

                {(createAttempted &&
                  (localValidationError || projectCreateError)) ||
                registeredPathConflict ? (
                  <div className="projects-composer-error" role="alert">
                    <strong>Proje oluşturulamadı</strong>
                    <span>
                      {projectCreateErrorTr(
                        localValidationError ||
                          projectCreateError ||
                          "Bu proje yolu Factory'de zaten kayıtlı.",
                      )}
                    </span>
                  </div>
                ) : null}

                <div className="projects-composer-actions">
                  <button
                    type="submit"
                    className="projects-composer-primary"
                    disabled={
                      projectSubmitting ||
                      !newProjectNameLocal.trim() ||
                      !newProjectParentPath.trim() ||
                      Boolean(nameValidation.error) ||
                      registeredPathConflict
                    }
                  >
                    {projectSubmitting
                      ? "Oluşturuluyor..."
                      : "Projeyi Oluştur"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="projects-composer-panel">
                <label className="projects-composer-path-field">
                  <span>Proje kök klasörü</span>
                  <div className="projects-path-picker">
                    <input
                      value={existingProjectRootPath}
                      onChange={(event) =>
                        setExistingProjectRootPath(event.target.value)
                      }
                      placeholder="D:\AI-Projects\mevcut-proje"
                      required
                    />
                    <button
                      type="button"
                      className="projects-browse-btn"
                      onClick={() => void handleBrowseFolder()}
                      disabled={browsingFolder}
                    >
                      {browsingFolder
                        ? "Açılıyor..."
                        : "Proje kök klasörü seç"}
                    </button>
                  </div>
                </label>

                <p className="projects-composer-help">
                  Seçtiğiniz klasör doğrudan proje kökü olarak eklenir.
                  Alt klasör oluşturulmaz.
                </p>

                <div className="projects-composer-status-row">
                  <span className="projects-composer-status-label">
                    Durum
                  </span>
                  <strong
                    className={
                      existingHasGit === true
                        ? "tone-ok"
                        : existingHasGit === false
                          ? "tone-warn"
                          : ""
                    }
                  >
                    {inspectingPath
                      ? "Kontrol ediliyor..."
                      : existingHasGit === true
                        ? "Git bulundu"
                        : existingHasGit === false
                          ? "Git bulunamadı"
                          : existingProjectRootPath.trim()
                            ? "Klasör seçildi"
                            : "Klasör seçilmedi"}
                  </strong>
                  {existingCharacteristics.length > 0 ? (
                    <em>{existingCharacteristics.join(" · ")}</em>
                  ) : null}
                </div>

                {existingHasGit === false ? (
                  <div className="projects-composer-info" role="status">
                    Bu klasörde Git deposu bulunamadı. İstersen bu mevcut
                    klasörde Git deposu oluşturabilirsin.
                  </div>
                ) : null}

                {(createAttempted &&
                  (localValidationError || projectCreateError)) ||
                registeredPathConflict ? (
                  <div className="projects-composer-error" role="alert">
                    <strong>Proje eklenemedi</strong>
                    <span>
                      {projectCreateErrorTr(
                        localValidationError ||
                          projectCreateError ||
                          "Bu proje yolu Factory'de zaten kayıtlı.",
                      )}
                    </span>
                  </div>
                ) : null}

                <div className="projects-composer-actions">
                  <button
                    type="button"
                    className="projects-composer-primary"
                    disabled={
                      projectSubmitting ||
                      !existingProjectRootPath.trim() ||
                      registeredPathConflict ||
                      existingHasGit === false
                    }
                    onClick={() => handleAddExisting(false)}
                  >
                    {projectSubmitting ? "Ekleniyor..." : "Projeyi Ekle"}
                  </button>
                  {existingHasGit === false ? (
                    <button
                      type="button"
                      className="projects-composer-secondary"
                      disabled={
                        projectSubmitting ||
                        !existingProjectRootPath.trim() ||
                        registeredPathConflict
                      }
                      onClick={() => handleAddExisting(true)}
                    >
                      {projectSubmitting
                        ? "Ekleniyor..."
                        : "Git Oluştur ve Ekle"}
                    </button>
                  ) : null}
                </div>
              </div>
            )}
          </form>
        )}

        <div className="projects-card-list">
          {cards.length === 0 ? (
            <div className="projects-empty">
              Henüz proje yok. Sağ paneldan yeni proje ekleyebilirsin.
            </div>
          ) : (
            cards.map(
              ({
                project,
                kind,
                meta,
                projectTasks,
                running,
                health,
                healthLabel,
                healthScore,
              }) => {
                const selectedCard =
                  selected?.project_id === project.project_id
                return (
                  <article
                    key={project.project_id}
                    className={`project-card health-${health} ${
                      selectedCard ? "selected" : ""
                    }`}
                    onClick={() => onSelectProject(project.project_id)}
                  >
                    <ProjectScene
                      kind={kind}
                      active={running || selectedCard}
                    />

                    <div className="project-card-body">
                      <div className="project-card-headline">
                        <div className="project-card-copy">
                          <span className="project-status">
                            <i />
                            Aktif
                          </span>
                          <h3>{project.name}</h3>
                          <p>{meta.blurb}</p>
                          <div className="project-tags">
                            {meta.tags.map((tag) => (
                              <span key={tag}>{tag}</span>
                            ))}
                          </div>
                        </div>
                        <HealthBadge
                          score={healthScore}
                          label={healthLabel}
                          tone={health}
                        />
                      </div>

                      <div className="project-meta-row">
                        <span title={project.path}>
                          <MiniIcon name="git" />
                          {shortPath(project.path)}
                        </span>
                        <span>
                          <MiniIcon name="branch" />
                          {selectedCard
                            ? controlCenter?.git.branch ?? "—"
                            : "—"}
                        </span>
                        <span>
                          <MiniIcon name="tasks" />
                          {projectTasks.length}
                          {projectTasks.length > 0 ? (
                            <b>
                              +{Math.min(projectTasks.length, 12)}
                            </b>
                          ) : null}
                        </span>
                        <span>
                          <MiniIcon name="clock" />
                          {relativeTime(
                            project.updated_at ??
                              project.created_at ??
                              projectTasks[0]?.started_at,
                          )}
                        </span>
                      </div>

                      <div className="project-card-actions">
                        <button
                          type="button"
                          className="project-open"
                          onClick={(event) => {
                            event.stopPropagation()
                            void handleOpen(project.project_id)
                          }}
                          disabled={openingId === project.project_id}
                        >
                          {openingId === project.project_id
                            ? "Açılıyor..."
                            : "Projeyi Aç"}
                          <MiniIcon name="arrow" />
                        </button>
                        <button
                          type="button"
                          className="project-details"
                          onClick={(event) => {
                            event.stopPropagation()
                            onSelectProject(project.project_id)
                            setViewMode("details")
                          }}
                        >
                          Ayrıntılar
                        </button>
                        <button
                          type="button"
                          className="project-remove"
                          title="Projeyi Kaldır"
                          aria-label={`${project.name} projesini kaldır`}
                          onClick={(event) => {
                            event.stopPropagation()
                            requestDelete(project)
                          }}
                          disabled={projectDeleting}
                        >
                          Projeyi Kaldır
                        </button>
                      </div>
                    </div>
                  </article>
                )
              },
            )
          )}
        </div>
      </div>

      <aside className="projects-side">
        <section className="projects-side-card">
          <div className="projects-side-head row">
            <div>
              <span>PROJE BİLGİSİ</span>
              <h3>Seçili Proje</h3>
            </div>
            <button
              type="button"
              className="projects-side-new"
              onClick={() => {
                if (!showComposer) {
                  setCreateAttempted(false)
                }
                setShowComposer((v) => !v)
              }}
            >
              {showComposer ? "Kapat" : "+ Yeni Proje"}
            </button>
          </div>

          {selected ? (
            <>
              <div className="projects-side-hero">
                <div className="projects-side-avatar">
                  <FactoryBear
                    variant={selectedMeta.variant}
                    mood="idle"
                    facing="toward"
                    portrait
                  />
                </div>
                <div>
                  <strong>{selected.name}</strong>
                  <em>
                    <i />
                    {selectedHealth?.healthLabel ?? "Aktif"}
                  </em>
                </div>
              </div>

              <dl className="projects-side-facts">
                <div>
                  <dt>Repo yolu</dt>
                  <dd title={selected.path}>{shortPath(selected.path)}</dd>
                </div>
                <div>
                  <dt>Aktif dal</dt>
                  <dd>{controlCenter?.git.branch ?? "—"}</dd>
                </div>
                <div>
                  <dt>Oluşturma</dt>
                  <dd>{relativeTime(selected.created_at)}</dd>
                </div>
                <div>
                  <dt>Durum</dt>
                  <dd>
                    <span className="projects-pill">
                      {selectedHealth?.healthLabel ?? "Sağlıklı"}
                    </span>
                  </dd>
                </div>
              </dl>
            </>
          ) : (
            <p className="projects-side-empty">Detay için bir proje seç.</p>
          )}
        </section>

        <section className="projects-side-card">
          <div className="projects-side-head">
            <span>PROJE AYARLARI</span>
            <h3>Ayarlar</h3>
          </div>

          <form
            className="projects-settings-form"
            onSubmit={onSaveProjectSettings}
          >
            <label>
              <span>Proje adı</span>
              <input
                value={projectSettingsName}
                onChange={(event) =>
                  onProjectSettingsNameChange(event.target.value)
                }
                disabled={!selected}
              />
            </label>
            <label>
              <span>Proje yolu</span>
              <input
                value={projectSettingsPath}
                onChange={(event) =>
                  onProjectSettingsPathChange(event.target.value)
                }
                disabled={!selected}
              />
            </label>
            <button
              type="submit"
              disabled={!selected || projectSettingsSaving}
            >
              {projectSettingsSaving
                ? "Kaydediliyor..."
                : "Değişiklikleri Kaydet"}
            </button>
          </form>
          {selected ? (
            <div className="projects-danger-zone">
              <p>
                Factory kaydını kaldırır; diskteki dosyalar korunur.
              </p>
              <button
                type="button"
                className="project-remove"
                onClick={() => requestDelete(selected)}
                disabled={projectDeleting}
              >
                Projeyi Kaldır
              </button>
            </div>
          ) : null}
        </section>

        <section className="projects-side-card">
          <div className="projects-side-head">
            <span>AKTİVİTE</span>
            <h3>Son Görevler</h3>
          </div>

          {selectedTasks.length === 0 ? (
            <p className="projects-side-empty">
              Bu projede henüz görev yok.
            </p>
          ) : (
            <ul className="projects-recent-tasks">
              {selectedTasks.map((task) => (
                <li key={task.task_id}>
                  <div className="projects-task-icon">
                    <OpsIcon name="tasks" />
                  </div>
                  <div>
                    <strong>
                      {(task.prompt || task.task_id).slice(0, 42)}
                      {(task.prompt || "").length > 42 ? "…" : ""}
                    </strong>
                    <small>
                      {taskStateLabel(task.state)} ·{" "}
                      {relativeTime(task.started_at)}
                    </small>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
        </>
      )}
    </div>
  )
}
