import { useQuery } from '@tanstack/react-query'
import { getLiveness } from '../../../shared/api/client'

export function ServiceStatus() {
  const query = useQuery({ queryKey: ['liveness'], queryFn: ({ signal }) => getLiveness(signal) })
  return (
    <section className="service-status" aria-label="服务连接">
      <p role="status">
        {query.isPending ? '正在连接服务…' : query.isError ? '暂时无法连接服务' : 'API 连接正常'}
      </p>
      <button type="button" onClick={() => void query.refetch()} disabled={query.isFetching}>
        {query.isFetching ? '检测中…' : '重新检测'}
      </button>
    </section>
  )
}
