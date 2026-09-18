export type Task = {
  task_id: string
  status: string
  prompt: string
  max_attempts: number
  project_id: string | null
  state: string
  model: string | null
  attempt: number
  test_result: string | null
  started_at: string | null
  task_kind?: "read" | "write" | null
}

export type Project = {
  project_id: string
  name: string
  path: string
  created_at: string | null
  updated_at: string | null
}

export type TaskDiff = {
  task_id: string
  diff: string
}


export type TaskReadResult = {
  task_id: string
  state: string
  result: string | null
}

export type PipelineStage = {
  id: string
  label: string
  status:
    | "pending"
    | "active"
    | "success"
    | "failed"
    | "waiting"
    | "rejected"
}

export type TaskPipeline = {
  task_id: string
  task_state: string
  current_stage: string
  progress_percent: number
  stages: PipelineStage[]
}

export type ControlCenterStatus = {
  generated_at: string
  system: {
    platform: string
    platform_release: string
    python_version: string
    cpu: {
      logical_count: number | null
      used_percent: number | null
    }
    memory: {
      available: boolean
      total_bytes: number | null
      available_bytes: number | null
      used_percent: number | null
    }
    disk: {
      total_bytes: number | null
      used_bytes: number | null
      free_bytes: number | null
      used_percent: number | null
    }
  }
  services: {
    docker: {
      installed: boolean
      online: boolean
      version: string | null
    }
    ollama: {
      installed: boolean
      online: boolean
      models: Array<{
        name: string
        size: number | null
        modified_at: string | null
      }>
    }
  }
  git: {
    available: boolean
    branch: string | null
    commit: string | null
    clean: boolean | null
  }
  tasks: {
    total: number
    running: number
    approval: number
    failed: number
    approved: number
  }
}

const API_BASE = "/api"

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  })

  if (!response.ok) {
    let message = `HTTP ${response.status}`

    try {
      const data = await response.json()
      message = data.detail ?? message
    } catch {
      // Keep generic HTTP error.
    }

    throw new Error(message)
  }

  return response.json() as Promise<T>
}

export function listTasks(
  projectId?: string | null,
) {
  const query = projectId
    ? `?project_id=${encodeURIComponent(projectId)}`
    : ""

  return request<Task[]>(`/tasks${query}`)
}

export function createTask(
  prompt: string,
  maxAttempts: number,
  projectId: string,
  model: string | null = null,
) {
  return request<Task>("/tasks", {
    method: "POST",
    body: JSON.stringify({
      prompt,
      max_attempts: maxAttempts,
      project_id: projectId,
      model,
    }),
  })
}

export function getTaskDiff(taskId: string) {
  return request<TaskDiff>(`/tasks/${taskId}/diff`)
}


export function getTaskResult(taskId: string) {
  return request<TaskReadResult>(
    `/tasks/${taskId}/result`,
  )
}

export function approveTask(taskId: string) {
  return request<Task>(`/tasks/${taskId}/approve`, {
    method: "POST",
  })
}

export function rejectTask(taskId: string) {
  return request<Task>(`/tasks/${taskId}/reject`, {
    method: "POST",
  })
}

export function retryTask(taskId: string) {
  return request<Task>(`/tasks/${taskId}/retry`, {
    method: "POST",
  })
}



export function listProjects() {
  return request<Project[]>("/projects")
}


export function createProject(
  name: string,
  path: string,
) {
  return request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify({
      name,
      path,
    }),
  })
}


export function updateProject(
  projectId: string,
  name: string,
  path: string,
) {
  return request<Project>(
    `/projects/${projectId}`,
    {
      method: "PUT",
      body: JSON.stringify({
        name,
        path,
      }),
    },
  )
}


export function deleteProject(
  projectId: string,
) {
  return fetch(
    `${API_BASE}/projects/${projectId}`,
    {
      method: "DELETE",
    },
  ).then((response) => {
    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status}`,
      )
    }
  })
}



export function getControlCenterStatus(
  projectId?: string | null,
) {
  const query = projectId
    ? `?project_id=${encodeURIComponent(projectId)}`
    : ""

  return request<ControlCenterStatus>(
    `/control-center/status${query}`,
  )
}


export function getTaskPipeline(
  taskId: string,
) {
  return request<TaskPipeline>(
    `/tasks/${taskId}/pipeline`,
  )
}



export function openProject(
  projectId: string,
) {
  return request<{ ok: boolean; project_id: string }>(
    `/projects/${projectId}/open`,
    {
      method: "POST",
    },
  )
}


export function openProjectTerminal(
  projectId: string,
) {
  return request<{ ok: boolean; project_id: string }>(
    `/projects/${projectId}/terminal`,
    {
      method: "POST",
    },
  )
}



export type ModelTestResult = {
  model: string
  response: string
  duration_ms: number
  done: boolean
}

export function testModel(
  model: string,
  prompt: string,
) {
  return request<ModelTestResult>(
    "/models/test",
    {
      method: "POST",
      body: JSON.stringify({
        model,
        prompt,
      }),
    },
  )
}
