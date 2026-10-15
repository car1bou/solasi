export class ApiError extends Error {
  status:number;
  constructor(message:string,status:number){super(message);this.name='ApiError';this.status=status;}
}
let csrf = '';
let connection: Promise<void> | null = null;
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (path !== '/bootstrap' && path !== '/client') await connect();
  const headers = new Headers(options.headers);
  if (options.body && typeof options.body === 'string') headers.set('Content-Type', 'application/json');
  if (csrf) headers.set('X-Session-Token', csrf);
  const response = await fetch('/api' + path, {...options, headers, credentials: 'same-origin'});
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(typeof error.detail === 'string' ? error.detail : '입력 정보를 확인하세요.', response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export function connect(): Promise<void> {
  if (!connection) connection = (async () => {
    const token = new URLSearchParams(location.hash.slice(1)).get('bootstrap');
    history.replaceState(null, '', location.pathname);
    const result = token
      ? await api<{csrf_token: string}>('/bootstrap', {method: 'POST', body: JSON.stringify({token})})
      : await api<{csrf_token: string}>('/client');
    csrf = result.csrf_token;
  })();
  return connection;
}
export function sessionToken(): string {return csrf;}
