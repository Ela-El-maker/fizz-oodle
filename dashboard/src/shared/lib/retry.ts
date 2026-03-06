export async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export function shouldRetry(status: number): boolean {
  return [429, 503, 504].includes(status);
}
