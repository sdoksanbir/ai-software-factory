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
) {
  return request<Task>("/tasks", {
    method: "POST",
    body: JSON.stringify({
      prompt,
      max_attempts: maxAttempts,
      project_id: projectId,
    }),
  })
}

export function getTaskDiff(taskId: string) {
  return request<TaskDiff>(`/tasks/${taskId}/diff`)
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
