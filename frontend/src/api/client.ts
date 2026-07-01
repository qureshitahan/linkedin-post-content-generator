import type { HealthStatus, Objective, Principle, RunSettings, Topic } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';
export const MAX_OBJECTIVE_LENGTH = 15000;

export function formatApiErrorDetail(detail: unknown, status?: number): string {
  if (typeof detail === 'string') return detail;

  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object' && 'msg' in item) {
        const loc = 'loc' in item && Array.isArray(item.loc) ? item.loc.join('.') : '';
        const msg = String((item as { msg: string }).msg);
        if (msg.includes('at most') && loc.includes('text')) {
        return `Objective is too long (max ${MAX_OBJECTIVE_LENGTH.toLocaleString()} characters). Please shorten your text.`;
        }
        return loc ? `${msg} (${loc})` : msg;
      }
      return null;
    }).filter(Boolean);
    if (messages.length > 0) return messages.join('; ');
  }

  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: string }).message);
  }

  return status ? `Request failed (${status}). Please try again.` : 'Request failed. Please try again.';
}

export function friendlyApiError(message: string): string {
  if (message === 'Not Found') {
    return 'The server does not have this feature yet. Hard refresh the page, or wait a minute if a deploy just finished.';
  }
  return message;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(formatApiErrorDetail(error.detail, response.status));
  }

  return response.json();
}

export const api = {
  health: () => request<HealthStatus>('/health'),

  createObjective: (text: string, principleId?: number | null) =>
    request<Objective>('/objectives', {
      method: 'POST',
      body: JSON.stringify({ text, principle_id: principleId ?? null }),
    }),

  analyzeObjective: (id: number, runSettings?: RunSettings) =>
    request<{ objective: Objective; message: string }>(`/objectives/${id}/analyze`, {
      method: 'POST',
      body: JSON.stringify({ run_settings: runSettings ?? null }),
    }),

  getObjective: (id: number) => request<Objective>(`/objectives/${id}`),

  listObjectives: () => request<Objective[]>('/objectives'),

  clearObjectives: () =>
    request<{ deleted: number }>('/objectives', { method: 'DELETE' }),

  deleteObjective: (id: number) =>
    request<{ deleted: number }>(`/objectives/${id}`, { method: 'DELETE' }),

  listPrinciples: () => request<Principle[]>('/principles'),

  createPrinciple: (name: string, description?: string) =>
    request<Principle>('/principles', {
      method: 'POST',
      body: JSON.stringify({ name, description: description ?? null }),
    }),

  deletePrinciple: (id: number) =>
    request<{ deleted: number }>(`/principles/${id}`, { method: 'DELETE' }),

  uploadPrincipleDocument: async (principleId: number, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(`${API_BASE}/principles/${principleId}/documents`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(formatApiErrorDetail(error.detail, response.status));
    }
    return response.json();
  },

  deletePrincipleDocument: (principleId: number, documentId: number) =>
    request<{ deleted: number }>(`/principles/${principleId}/documents/${documentId}`, {
      method: 'DELETE',
    }),

  regenerateDraft: (objectiveId: number, topicId: number, draftIndex = 0) =>
    request<Topic>(
      `/objectives/${objectiveId}/topics/${topicId}/regenerate-draft?draft_index=${draftIndex}`,
      { method: 'POST' },
    ),

  generateDrafts: (objectiveId: number, topicId: number, styles: string[]) =>
    request<Topic>(`/objectives/${objectiveId}/topics/${topicId}/generate-drafts`, {
      method: 'POST',
      body: JSON.stringify({ styles }),
    }),

  generateImage: (
    objectiveId: number,
    topicId: number,
    body: {
      draft_text: string;
      topic_name?: string;
      mode?: 'new' | 'edit';
      custom_prompt?: string;
      previous_prompt?: string;
      edit_instruction?: string;
    },
  ) =>
    request<{ image_url: string; prompt_used: string; filename: string }>(
      `/objectives/${objectiveId}/topics/${topicId}/generate-image`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
};
