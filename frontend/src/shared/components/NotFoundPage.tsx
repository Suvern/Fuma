import { Panel } from "../ui/controls";
import { Link } from "react-router";
import { PageTitle } from "./PageTitle";

export function Component() {
  return (
    <Panel className="panel">
      <PageTitle title="页面不存在">页面不存在</PageTitle>
      <p>链接可能有误，请返回分发页。</p>
      <Link to="/">返回分发页</Link>
    </Panel>
  );
}
