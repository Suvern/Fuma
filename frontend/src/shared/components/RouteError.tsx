import { PageTitle } from './PageTitle'

export function RouteError() {
  return (
    <main className="panel">
      <PageTitle title="页面加载失败">页面加载失败</PageTitle>
      <p>请重新加载页面后再试。</p>
      <a href="/">重新打开分发页</a>
    </main>
  )
}
