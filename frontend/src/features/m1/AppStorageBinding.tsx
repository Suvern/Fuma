import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { read, write, type DTO } from "../../shared/api/http";
import { Select } from "../../shared/ui/FormControls";
import { ErrorBox, Field, Form, Loading, useCommand } from "../../shared/ui/common";
import { Button, Panel } from "../../shared/ui/controls";
import { Link } from "react-router";

type Channel = "debug" | "release";
type Draft = Record<`${Channel}StorageId` | `${Channel}Prefix`, string>;

const emptyDraft: Draft = {
  debugStorageId: "",
  debugPrefix: "debug",
  releaseStorageId: "",
  releasePrefix: "release",
};

function draftFrom(
  value: DTO<"PackageStorageBindings"> | undefined,
): Draft {
  return {
    debugStorageId: value?.debug?.storage_location_id ?? "",
    debugPrefix: value?.debug?.object_prefix ?? emptyDraft.debugPrefix,
    releaseStorageId: value?.release?.storage_location_id ?? "",
    releasePrefix: value?.release?.object_prefix ?? emptyDraft.releasePrefix,
  };
}

function normalizedPrefix(value: string) {
  return value.trim().replace(/^\/+|\/+$/g, "");
}

export function AppStorageBinding({ appId }: { appId: string }) {
  const client = useQueryClient();
  const cmd = useCommand();
  const bindings = useQuery({
    queryKey: ["app-package-storage", appId],
    queryFn: () => read("/api/v1/apps/{id}/package-storage", { id: appId }),
  });
  const available = useQuery({
    queryKey: ["app-available-storage", appId],
    queryFn: () => read("/api/v1/apps/{id}/available-storage", { id: appId }),
  });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>();
  const [validationError, setValidationError] = useState("");

  const options = useMemo(
    () => available.data?.items ?? [],
    [available.data?.items],
  );
  const saved = bindings.data;
  const currentDraft = draft ?? draftFrom(saved);
  const setDraftValue = (key: keyof Draft, value: string) => {
    setValidationError("");
    setDraft((current) => ({ ...(current ?? currentDraft), [key]: value }));
  };
  const channelLabel = (channel: Channel) =>
    channel === "debug" ? "Debug" : "Release";

  function submit() {
    const channels: Channel[] = ["debug", "release"];
    for (const channel of channels) {
      const storageId = currentDraft[`${channel}StorageId`];
      const prefix = normalizedPrefix(currentDraft[`${channel}Prefix`]);
      if (storageId && !prefix) {
        setValidationError(`${channelLabel(channel)} 已选择存储位置，请填写对象前缀。`);
        return;
      }
    }
    if (
      currentDraft.debugStorageId &&
      currentDraft.releaseStorageId &&
      currentDraft.debugStorageId === currentDraft.releaseStorageId
    ) {
      setValidationError("Debug 与 Release 必须使用不同存储桶。");
      return;
    }

    void cmd.run(
      "update-app-package-storage",
      () =>
        write(
          "/api/v1/apps/{id}/package-storage",
          "put",
          {
            debug: currentDraft.debugStorageId
              ? {
                  storage_location_id: currentDraft.debugStorageId,
                  object_prefix: normalizedPrefix(currentDraft.debugPrefix),
                }
              : null,
            release: currentDraft.releaseStorageId
              ? {
                  storage_location_id: currentDraft.releaseStorageId,
                  object_prefix: normalizedPrefix(currentDraft.releasePrefix),
                }
              : null,
          },
          { id: appId, revision: saved?.app_revision },
        ),
      (updated) => {
        client.setQueryData(["app-package-storage", appId], updated);
        setDraft(undefined);
        setEditing(false);
      },
      "包存储绑定已保存。",
    );
  }

  if (bindings.isPending || available.isPending) return <Loading />;
  return (
    <Panel>
      <div className="settings-section-heading">
        <h2>分发存储绑定</h2>
        {!editing && (
          <Button
            type="button"
            aria-label="修改包存储绑定"
            onClick={() => {
              setDraft(draftFrom(saved));
              setValidationError("");
              setEditing(true);
            }}
          >
            修改
          </Button>
        )}
      </div>
      <p className="muted settings-edit-hint">
        这是此 App 的唯一包来源配置。Debug 和 Release 必须分别绑定独立存储桶；COS 上传、通知接收、
        手工上传和补导入都会严格按当前 channel 使用这里的绑定。尚未配置时，对应 channel 不能接收或导入安装包。
      </p>
      {cmd.feedback}
      <ErrorBox error={bindings.error ?? available.error} />
      {validationError && (
        <p role="alert" className="field-error">
          {validationError}
        </p>
      )}
      {!bindings.error && !available.error && (
        <Form submit={submit}>
          {(["debug", "release"] as Channel[]).map((channel) => {
            const storageId = currentDraft[`${channel}StorageId`];
            return (
              <fieldset key={channel} disabled={!editing || cmd.pending}>
                <legend>{channelLabel(channel)} 包源</legend>
                <Select
                  name={`${channel}-storage-location`}
                  label={`${channelLabel(channel)} 包源存储桶`}
                  value={storageId}
                  onChange={(event) =>
                    setDraftValue(
                      `${channel}StorageId`,
                      event.target.value,
                    )
                  }
                >
                  <option value="">暂不绑定</option>
                  {options.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} · {item.provider.toUpperCase()} · {item.read_mode}
                    </option>
                  ))}
                </Select>
                <Field
                  name={`${channel}-object-prefix`}
                  label="对象前缀"
                  value={currentDraft[`${channel}Prefix`]}
                  onChange={(event) =>
                    setDraftValue(
                      `${channel}Prefix`,
                      event.target.value,
                    )
                  }
                  required={Boolean(storageId)}
                  maxLength={200}
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  help="相对于资源池路径前缀的目录名；此 App 的该 channel 只会读取和写入这个前缀。"
                />
              </fieldset>
            );
          })}
          {editing && (
            <div className="form-actions">
              <Button
                type="button"
                disabled={cmd.pending}
                onClick={() => {
                  setDraft(undefined);
                  setValidationError("");
                  setEditing(false);
                }}
              >
                取消修改
              </Button>
              <Button className="primary" loading={cmd.pending}>
                保存绑定
              </Button>
            </div>
          )}
        </Form>
      )}
      {!options.length && !available.error && (
        <p className="muted">
          暂无已启用且通过连接测试的存储桶资源，请先到 <Link to="/admin/settings/storage">存储桶资源池</Link> 登记并测试。
        </p>
      )}
    </Panel>
  );
}
