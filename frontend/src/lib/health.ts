import { useQuery } from '@tanstack/react-query'

/** Camera đang tạm tắt (CAMERA_ENABLED=false) -> ẩn mọi mục camera trên giao diện. */
export function useCameraEnabled(): boolean {
  const q = useQuery({
    queryKey: ['health'], staleTime: 3600_000,
    queryFn: () => fetch('/health').then((r) => r.json() as Promise<{ camera_enabled: boolean }>),
  })
  return !!q.data?.camera_enabled
}
