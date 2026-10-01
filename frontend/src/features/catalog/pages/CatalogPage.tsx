import { PageTitle } from '../../../shared/components/PageTitle'
import { ServiceStatus } from '../../system/components/ServiceStatus'

export function Component() {
  return (
    <section className="panel">
      <p className="eyebrow">M1 · 开发中</p>
      <PageTitle title="安装包分发">团队安装包，集中分发。</PageTitle>
      <p>Debug 包浏览、飞书登录和临时下载正在开发中，当前尚未开放下载。</p>
      <ServiceStatus />
    </section>
  )
}
