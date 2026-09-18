export type Task = {
  task_id: string
  status: string
  prompt: string
  max_attempts: number
  state: string
  model: string | null
  attempt: number
  test_result: string | null
  started_at: string | null
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

export function listTasks() {
  return request<Task[]>("/tasks")
}

export function createTask(
  prompt: string,
  maxAttempts: number,
) {
  return request<Task>("/tasks", {
    method: "POST",
    body: JSON.stringify({
      prompt,
      max_attempts: maxAttempts,
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
