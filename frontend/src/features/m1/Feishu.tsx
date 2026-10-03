import { confirmAction } from "../../shared/ui/confirm";
import { Button, Panel, Input, Notice } from "../../shared/ui/controls";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { read, write, type DTO } from "../../shared/api/http";
import {
  Check,
  Checks,
  Empty,
  ErrorBox,
  Field,
  Form,
  Loading,
  Pager,
  Status,
  TaskNotice,
  Title,
  date,
  text,
  useCommand,
  useFilters,
} from "../../shared/ui/common";
export function ChatPicker({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const filters = useFilters();
  const q = useQuery({
    queryKey: ["chats", filters.page, filters.q],
    queryFn: () =>
      read("/api/v1/settings/feishu-bot/chats", {
        query: { page: filters.page, q: filters.q },
      }),
    refetchInterval: (query) =>
      query.state.data?.sync_state === "syncing" ? 2500 : false,
  });
  return (
    <div className="chat-picker">
      <h3>选择机器人所在群</h3>
      {filters.search}
      <p className="muted">
        已选择 {selected.length} 个群；跨搜索与分页保留选择。
        {selected.length > 0 && (
          <Button type="button" onClick={() => onChange([])}>
            清空选择
          </Button>
        )}
      </p>
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.data && (
        <div className="prose">
          同步：
          <Status value={q.data.sync_state} /> · {date(q.data.synced_at)}{" "}
          {q.data.sync_error_code}
        </div>
      )}
      <div className="chat-list">
        {q.data?.items.map((chat) => (
          <div key={chat.chat_id} className="chat-row">
            <Check
              label={chat.name}
              checked={selected.includes(chat.chat_id)}
              disabled={chat.membership !== "joined"}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? [...selected, chat.chat_id]
                    : selected.filter((id) => id !== chat.chat_id),
                )
              }
            />
            <Status value={chat.membership} />
            <Status value={chat.send_status} />
          </div>
        ))}
      </div>
      {q.data && !q.data.items.length && (
        <Empty>没有符合条件的群，请先将机器人加入群聊并同步。</Empty>
      )}
      <Pager data={q.data} {...filters} />
    </div>
  );
}
export function FeishuPage() {
  const q = useQuery({
    queryKey: ["feishu"],
    queryFn: () => read("/api/v1/settings/feishu"),
  });
  if (q.isPending) return <Loading />;
  if (!q.data) return <ErrorBox error={q.error} />;
  return <FeishuEditor key={q.data.revision} config={q.data} />;
}
function FeishuEditor({ config: c }: { config: DTO<"FeishuConfig"> }) {
  const cmd = useCommand();
  const [proof, setProof] = useState<DTO<"FeishuBindingProof">>();
  const [result, setResult] = useState<DTO<"ConnectionTestResult">>();
  return (
    <>
      <Title description="每个部署绑定一个飞书租户；SSO 与通知机器人复用同一个企业自建应用。">
        飞书集成
      </Title>
      <Panel className="panel">
        <h2>1. 企业自建应用</h2>
        <p>
          在飞书开放平台创建企业自建应用，配置网页登录回调、启用机器人，并将应用发布到需要的可用范围。
        </p>
        <label className="field">
          OAuth 回调地址
          <Input readOnly value={c.callback_url} />
        </label>
        <p>
          租户：{c.tenant_key ?? "尚未绑定"} ·{" "}
          {c.verified ? "已验证" : "等待管理员验证"} ·{" "}
          {c.has_secret ? "已保存密钥" : "未配置密钥"}
        </p>
        {cmd.feedback}
        <Form
          submit={(f) =>
            void cmd.run("feishu-config", () =>
              write(
                "/api/v1/settings/feishu",
                "put",
                {
                  app_id: text(f, "app_id"),
                  enabled: f.has("enabled"),
                  ...(text(f, "app_secret")
                    ? { app_secret: text(f, "app_secret") }
                    : {}),
                },
                { revision: c.revision },
              ),
            )
          }
        >
          <Field
            name="app_id"
            label="App ID"
            defaultValue={c.app_id ?? ""}
            required
            maxLength={128}
          />
          <Field
            name="app_secret"
            label="App Secret"
            type="password"
            autoComplete="off"
            required={!c.has_secret}
            minLength={16}
            help="留空保留现有密钥；修改应用后需重新验证租户。"
          />
          <Check
            name="enabled"
            label="启用飞书 SSO"
            defaultChecked={c.enabled}
          />
          <Button className="primary" disabled={cmd.pending}>
            保存应用配置
          </Button>
        </Form>
        <Button
          disabled={cmd.pending}
          onClick={() =>
            void cmd.run(
              "feishu-test",
              () => write("/api/v1/settings/feishu/test", "post", undefined),
              setResult,
            )
          }
        >
          测试应用凭据
        </Button>
        <Checks checks={result?.checks ?? c.checks} />
      </Panel>
      <Panel className="panel">
        <h2>2. 管理员验证租户</h2>
        <p>
          使用候选应用进行飞书授权，返回此页面后读取验证结果并确认绑定。管理员会话将保留。
        </p>
        <div className="toolbar">
          <Button
            disabled={cmd.pending || !c.app_id || !c.has_secret}
            onClick={() =>
              void cmd.run(
                "binding-start",
                () =>
                  write("/api/v1/settings/feishu/binding/start", "post", {
                    return_to: "/admin/settings/feishu",
                  }),
                (result) => window.location.assign(result.authorization_url),
              )
            }
          >
            开始飞书验证
          </Button>
          <Button
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run(
                "binding-proof",
                () => read("/api/v1/settings/feishu/binding/proof"),
                setProof,
              )
            }
          >
            读取返回的验证结果
          </Button>
        </div>
        {proof && (
          <Notice className="notice">
            <p>
              应用：{proof.app_id} · 租户：{proof.tenant_key}
            </p>
            <p>
              验证人：{proof.display_name} · 过期时间：{date(proof.expires_at)}
            </p>
            <Button
              className="primary"
              disabled={cmd.pending || proof.consumed}
              onClick={() =>
                void cmd.run("binding-confirm", () =>
                  write(
                    "/api/v1/settings/feishu/binding/confirm",
                    "post",
                    { binding_id: proof.binding_id },
                    { revision: c.revision },
                  ),
                )
              }
            >
              确认绑定此租户
            </Button>
          </Notice>
        )}
      </Panel>
      <BotSection />
    </>
  );
}
function BotSection() {
  const q = useQuery({
    queryKey: ["bot"],
    queryFn: () => read("/api/v1/settings/feishu-bot"),
  });
  const cmd = useCommand();
  const [selected, setSelected] = useState<string[]>([]);
  const [task, setTask] = useState<DTO<"TaskAccepted">>();
  const [result, setResult] = useState<DTO<"ConnectionTestResult">>();
  return (
    <Panel className="panel">
      <h2>3. 单机器人与通知群</h2>
      <ErrorBox error={q.error} />
      {cmd.feedback}
      <TaskNotice task={task} />
      {q.data && (
        <>
          <p>
            机器人：{q.data.bot_name ?? "未识别"} · App ID：
            {q.data.app_id ?? "未绑定"} ·{" "}
            {q.data.verified ? "已验证" : "待验证"}
          </p>
          <div className="toolbar">
            <Button
              disabled={cmd.pending}
              onClick={() =>
                void cmd.run("bot-enabled", () =>
                  write(
                    "/api/v1/settings/feishu-bot",
                    "put",
                    { enabled: !q.data!.enabled },
                    { revision: q.data!.revision },
                  ),
                )
              }
            >
              {q.data.enabled ? "停用机器人" : "启用机器人"}
            </Button>
            <Button
              disabled={cmd.pending}
              onClick={() =>
                void cmd.run(
                  "bot-test",
                  () =>
                    write(
                      "/api/v1/settings/feishu-bot/test",
                      "post",
                      undefined,
                    ),
                  setResult,
                )
              }
            >
              检查机器人能力
            </Button>
            <Button
              disabled={cmd.pending}
              onClick={() =>
                void cmd.run(
                  "chat-sync",
                  (key) =>
                    write(
                      "/api/v1/settings/feishu-bot/chats/refresh",
                      "post",
                      undefined,
                      { key },
                    ),
                  setTask,
                )
              }
            >
              同步所在群聊
            </Button>
          </div>
          <Checks checks={result?.checks ?? q.data.checks} />
        </>
      )}
      <ChatPicker selected={selected} onChange={setSelected} />
      <Button
        className="primary"
        disabled={cmd.pending || !selected.length}
        onClick={async () => {
          if (
            await confirmAction(`向所选 ${selected.length} 个群发送测试卡片？`)
          )
            void cmd.run(
              `bot-message-${selected.join(",")}`,
              (key) =>
                write(
                  "/api/v1/settings/feishu-bot/test-message",
                  "post",
                  { chat_ids: selected },
                  { key },
                ),
              setTask,
            );
        }}
      >
        发送测试卡片到所选群
      </Button>
      <p className="muted">
        发送结果记录在通知中心。群名单仅包含机器人所在群。
      </p>
    </Panel>
  );
}
