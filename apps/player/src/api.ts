export interface Me {
  id: number;
  tg_id: number;
  first_name: string;
  username: string | null;
  language_code: string | null;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function fetchMe(initData: string): Promise<Me> {
  const response = await fetch("/api/me", { headers: { Authorization: `tma ${initData}` } });
  if (!response.ok) {
    throw new ApiError(response.status, `GET /api/me: ${response.status}`);
  }
  return (await response.json()) as Me;
}
