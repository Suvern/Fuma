import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { read } from "../../shared/api/http";
import { Button, Panel } from "../../shared/ui/controls";
import {
  ErrorBox,
  Field,
  Form,
  Loading,
  size,
  text,
} from "../../shared/ui/common";

export function Statistics({ appId }: { appId: string }) {
  const today = new Date().toISOString().slice(0, 10);
  const [range, setRange] = useState(() => ({
    start_date: new Date(Date.now() - 29 * 86400000).toISOString().slice(0, 10),
    end_date: today,
  }));
  const query = useQuery({
    queryKey: ["distribution-statistics", appId, range],
    queryFn: () =>
      read("/api/v1/apps/{id}/distribution-statistics", {
        id: appId,
        query: range,
      }),
  });
  return (
    <Panel className="panel">
      <h2>正式包分发统计</h2>
      <p className="muted">
        按 UTC
        日期汇总，仅累计升级后记录。授权签发包含云直链，本机请求与字节不包含云直链传输和历史
        Debug 缓存。HEAD
        仅检查文件信息。已发送字节表示服务端观察到的响应数据，不代表客户端完整接收或安装量；范围重试可能重复计算字节。
      </p>
      <Form
        submit={(form) =>
          setRange({
            start_date: text(form, "start_date"),
            end_date: text(form, "end_date"),
          })
        }
      >
        <div className="inline">
          <Field
            name="start_date"
            type="date"
            label="统计开始日期"
            required
            defaultValue={range.start_date}
            max={today}
          />
          <Field
            name="end_date"
            type="date"
            label="统计结束日期"
            required
            defaultValue={range.end_date}
            max={today}
          />
          <Button disabled={query.isFetching}>查询</Button>
        </div>
        <p className="muted">单次最多查询 90 天。</p>
      </Form>
      <ErrorBox error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        query.data && (
          <>
            <p>
              授权签发 {query.data.totals.grant_count} 次 · 本机 GET{" "}
              {query.data.totals.local_get_requests} 次 · HEAD{" "}
              {query.data.totals.local_head_requests} 次 · 已发送{" "}
              {size(query.data.totals.observed_bytes)}
            </p>
            <details>
              <summary>查看每日明细</summary>
              <div style={{ overflowX: "auto" }}>
                <table>
                  <caption>每日服务端观测值，不等于安装量</caption>
                  <thead>
                    <tr>
                      {[
                        "日期（UTC）",
                        "授权签发",
                        "本机 GET",
                        "HEAD",
                        "206 分段 GET",
                        "GET 中断",
                        "已发送字节",
                      ].map((label) => (
                        <th key={label} scope="col">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {query.data.days.map((day) => (
                      <tr key={day.date}>
                        <th scope="row">{day.date}</th>
                        <td>{day.grant_count}</td>
                        <td>{day.local_get_requests}</td>
                        <td>{day.local_head_requests}</td>
                        <td>{day.partial_get_requests}</td>
                        <td>{day.interrupted_get_requests}</td>
                        <td>{size(day.observed_bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        )
      )}
    </Panel>
  );
}
