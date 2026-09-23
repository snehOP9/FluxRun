export const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path.startsWith('/api/') || path === '/readyz' ? path : '/api/v1' + path}`, { ...options, credentials: 'include', headers: { 'Content-Type': 'application/json', ...options.headers } });
  if (!response.ok) { const body = await response.json().catch(() => null); throw new ApiError(body?.error?.message || 'Server unavailable. Check the connection and retry.', response.status); }
  return response.status === 204 ? undefined as T : response.json();
}
export const send = <T,>(path: string, data: unknown = {}, method = 'POST') => api<T>(path, {method, body: JSON.stringify(data)});
export type User = {id:string; email:string; display_name:string};
export type Workspace = {id:string; name:string; slug:string; role:string};
export type Project = {id:string; name:string; slug:string; workspace_id:string; description:string|null; settings:Record<string,unknown>; role:string};
export type Page<T> = {items:T[]; page:{has_more:boolean; next_cursor:string|null}};
export type Experiment = {id:string; project_id:string; name:string; description:string|null; run_count:number; created_at:string};
export type Run = {id:string; experiment_id:string; project_id:string; name:string; status:string; started_at:string; ended_at:string|null; metrics:Record<string,number>; params:Record<string,unknown>; tags:Record<string,string>; source:Record<string,unknown>; error:string|null};
export type Artifact = {id:string; path:string; status:string; size:number; sha256:string; content_type:string};
export type Point = {step:number; value:number; timestamp:string};
export type Series = {points:Point[]; key:string; total_points:number; downsampling:string|null};
