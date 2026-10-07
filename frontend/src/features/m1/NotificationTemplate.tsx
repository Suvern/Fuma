import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { Button, PageTabs, Panel } from "../../shared/ui/controls";
import { Select, TextArea } from "../../shared/ui/FormControls";
import {
  ErrorBox,
  Field,
  Form,
  Loading,
  Title,
  useCommand,
} from "../../shared/ui/common";
import "./notification-template.css";

type Template = DTO<"ReleaseNotificationTemplate">;
type Config = DTO<"ReleaseNotificationTemplateConfig">;
type TextField = "title" | "body" | "button_text" | "sub_button_text";
const limits = { title: 100, body: 2000, button_text: 30, sub_button_text: 30 };
const labels = { title: "卡片标题", body: "卡片正文", button_text: "主按钮文案", sub_button_text: "次按钮文案" };
const colors: Record<Template["header_color"], string> = {
  blue: "蓝色",
  green: "绿色",
  orange: "橙色",
  red: "红色",
  purple: "紫色",
  grey: "灰色",
};

function fieldError(value: string, field: TextField, names: string[]) {
  if (!value.trim()) return `${labels[field]}不能为空`;
  if (Array.from(value).length > limits[field])
    return `最多 ${limits[field]} 个字`;
  let unknown = false;
  const rest = value.replace(/\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g, (_, name: string) => {
    if (!names.includes(name)) unknown = true;
    return "";
  });
  if (unknown || rest.includes("{{") || rest.includes("}}"))
    return "变量无效，请使用下方列出的 {{变量名}}";
  return "";
}

function preview(value: string, limit: number, variables: Config["variables"]) {
  const rendered = value
    .replace(
      /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g,
      (token, name: string) =>
        variables.find((v) => v.name === name)?.sample ?? token,
    )
    .trim();
  const chars = Array.from(rendered);
  return chars.length > limit
    ? chars.slice(0, limit - 1).join("") + "…"
    : rendered;
}

export function AppNotificationTemplatePage() {
  const { id = "" } = useParams();
  const app = useQuery({
    queryKey: ["app", id],
    queryFn: () => read("/api/v1/apps/{id}", { id }),
  });
  if (app.isPending) return <Loading />;
  if (!app.data) return <ErrorBox error={app.error} />;
  return (
    <>
      <Title description="管理此应用的安装包就绪通知，编辑时可实时预览卡片。">
        {`${app.data.name} · 飞书卡片`}
      </Title>
      <PageTabs><Link to={`/admin/apps/${id}`}>应用设置</Link></PageTabs>
      <NotificationTemplateSection key={id} appId={id} readOnly={!!app.data.archived_at} />
    </>
  );
}

export function NotificationTemplateSection({ appId, readOnly = false }: { appId: string; readOnly?: boolean }) {
  const q = useQuery({
    queryKey: ["release-notification-template", appId],
    queryFn: () => read("/api/v1/apps/{id}/release-notification-template", { id: appId }),
  });
  return (
    <Panel
      id="notification-template"
      aria-labelledby="notification-template-title"
    >
      <h2 id="notification-template-title">Release 通知卡片模板</h2>
      <p className="muted">
        仅用于当前应用经 GitHub Actions 上传 Release、安装包就绪后的飞书通知。
        独立保存，不影响其他应用；历史通知及其重试保留原内容。
      </p>
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.isError && (
        <Button type="button" onClick={() => void q.refetch()}>
          重新加载模板
        </Button>
      )}
      {readOnly && <p className="muted">应用已归档，模板仅可查看。恢复应用后可继续编辑。</p>}
      {q.data && <fieldset className="notification-template-fieldset" disabled={readOnly}>
        <TemplateEditor key={appId} config={q.data} appId={appId} />
      </fieldset>}
    </Panel>
  );
}

function TemplateEditor({ config, appId }: { config: Config; appId: string }) {
  const id = useId();
  const cmd = useCommand();
  const [saved, setSaved] = useState(config);
  const [draft, setDraft] = useState<Template>(config.template);
  const [touched, setTouched] = useState<Partial<Record<TextField, boolean>>>(
    {},
  );
  const names = config.variables.map((v) => v.name);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved.template);
  const errors = Object.fromEntries(
    (Object.keys(limits) as TextField[]).map((field) => [
      field,
      fieldError(draft[field], field, names),
    ]),
  ) as Record<TextField, string>;

  function change(field: TextField, value: string) {
    setDraft({ ...draft, [field]: value });
    setTouched({ ...touched, [field]: false });
  }
  function load(value: Config) {
    setSaved(value);
    setDraft(value.template);
    setTouched({});
  }

  return (
    <div className="notification-template-layout">
      <div>
        <Form
          submit={() => {
            setTouched({ title: true, body: true, button_text: true, sub_button_text: true });
            const invalid = (Object.keys(limits) as TextField[]).find(
              (field) => errors[field],
            );
            if (invalid) {
              document.getElementById(`${id}-${invalid}`)?.focus();
              return;
            }
            void cmd.run(
              "notification-template-save",
              () =>
                write(
                  "/api/v1/apps/{id}/release-notification-template",
                  "put",
                  draft,
                  { id: appId, revision: saved.revision },
                ),
              load,
              "模板已保存，将用于此应用新生成的 Release 成功通知。未发送任何消息。",
            );
          }}
        >
          <Field
            id={`${id}-title`}
            name="title"
            label="卡片标题"
            required
            maxLength={100}
            value={draft.title}
            disabled={cmd.pending}
            onChange={(e) => change("title", e.target.value)}
            onBlur={() => setTouched({ ...touched, title: true })}
          />
          {touched.title && errors.title && (
            <p role="alert" className="field-error">
              {errors.title}
            </p>
          )}
          <div className="field">
            <label htmlFor={`${id}-body`}>卡片正文 *</label>
            <TextArea
              id={`${id}-body`}
              name="body"
              required
              maxLength={2000}
              rows={10}
              value={draft.body}
              disabled={cmd.pending}
              onChange={(e) => change("body", e.target.value)}
              onBlur={() => setTouched({ ...touched, body: true })}
              aria-invalid={touched.body && !!errors.body}
              aria-describedby={`${id}-body-help`}
            />
            <small id={`${id}-body-help`}>
              支持换行和变量，按纯文本发送。最多 2000 字；替换后超长内容会省略。
            </small>
            {touched.body && errors.body && (
              <p role="alert" className="field-error">
                {errors.body}
              </p>
            )}
          </div>
          <Field
            id={`${id}-button_text`}
            name="button_text"
            label="主按钮文案"
            required
            maxLength={30}
            value={draft.button_text}
            disabled={cmd.pending}
            onChange={(e) => change("button_text", e.target.value)}
            onBlur={() => setTouched({ ...touched, button_text: true })}
            help="按钮始终指向该应用的安装包页面。"
          />
          {touched.button_text && errors.button_text && (
            <p role="alert" className="field-error">
              {errors.button_text}
            </p>
          )}
          <Field
            id={`${id}-sub_button_text`}
            name="sub_button_text"
            label="次按钮文案"
            required
            maxLength={30}
            value={draft.sub_button_text}
            disabled={cmd.pending}
            onChange={(e) => change("sub_button_text", e.target.value)}
            onBlur={() => setTouched({ ...touched, sub_button_text: true })}
            help="次按钮固定跳转到当前应用的下载页面。可编辑文案，链接由系统生成。"
          />
          {touched.sub_button_text && errors.sub_button_text && (
            <p role="alert" className="field-error">{errors.sub_button_text}</p>
          )}
          <div className="field">
            <Select
              id={`${id}-color`}
              label="标题颜色"
              name="header_color"
              value={draft.header_color}
              disabled={cmd.pending}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  header_color: e.target.value as Template["header_color"],
                })
              }
            >
              {Object.entries(colors).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </div>
          {cmd.feedback}
          <div className="toolbar">
            <Button
              className="primary"
              loading={cmd.pending}
              disabled={cmd.pending}
            >
              保存模板
            </Button>
            <Button
              type="button"
              disabled={cmd.pending}
              onClick={() => {
                setDraft(config.defaults);
                setTouched({});
              }}
            >
              恢复默认内容
            </Button>
            <Button
              type="button"
              disabled={cmd.pending || !dirty}
              onClick={() => load(saved)}
            >
              撤销修改
            </Button>
          </div>
          <p className="muted" role="status">
            {dirty ? "有未保存的修改" : "编辑后保存即可生效"} ·
            保存和预览不会发送消息。
          </p>
          <Button
            type="button"
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run(
                "notification-template-reload",
                () => read("/api/v1/apps/{id}/release-notification-template", { id: appId }),
                load,
                "已载入最新模板。",
                dirty ? "重新载入会丢弃未保存的修改，是否继续？" : undefined,
              )
            }
          >
            重新载入已保存模板
          </Button>
        </Form>
        <details className="notification-template-variables" open>
          <summary>可用变量</summary>
          <dl>
            {config.variables.map((variable) => (
              <div key={variable.name}>
                <dt>
                  <code>{`{{${variable.name}}}`}</code>
                </dt>
                <dd>{variable.label}</dd>
              </div>
            ))}
          </dl>
        </details>
      </div>
      <aside
        aria-label="通知卡片预览"
        className="notification-template-preview"
      >
        <h3>示例预览</h3>
        <p className="muted">
          使用当前应用与示例版本，实际消息会替换为本次 Release 数据。
        </p>
        <div
          className={`release-card-preview release-card-preview--${draft.header_color}`}
        >
          <div className="release-card-preview-title">
            {preview(draft.title, 100, config.variables) || config.sample.title}
          </div>
          <div className="release-card-preview-body">
            {preview(draft.body, 2000, config.variables) ||
              config.sample.summary}
          </div>
          <div className="release-card-preview-actions">
            <a className="release-card-preview-button" href={config.sample.page_url ?? undefined} target="_blank" rel="noreferrer">
              {preview(draft.button_text, 30, config.variables) || "查看安装包"}
            </a>
            <a className="release-card-preview-button release-card-preview-button--secondary" href={config.sample.page_url ?? undefined} target="_blank" rel="noreferrer">
              {preview(draft.sub_button_text, 30, config.variables) || "应用下载页"}
            </a>
          </div>
        </div>
      </aside>
    </div>
  );
}
