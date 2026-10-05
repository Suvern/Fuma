import { useEffect, useId, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import Button from "@douyinfe/semi-ui-19/lib/es/button";
import Select from "@douyinfe/semi-ui-19/lib/es/select";
import Space from "@douyinfe/semi-ui-19/lib/es/space";
import Tag from "@douyinfe/semi-ui-19/lib/es/tag";
import Typography from "@douyinfe/semi-ui-19/lib/es/typography";
import { IconGithubLogo } from "@douyinfe/semi-icons";
import { read } from "../api/http";
import { ErrorBox } from "./common";

/** The connector belongs in the query key so late responses never leak across accounts. */
export function RepositorySelect({
  connectorId,
  value,
  onChange,
  disabled = false,
}: {
  connectorId: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  const repos = useInfiniteQuery({
    queryKey: ["repository-options", connectorId, query],
    initialPageParam: 1,
    queryFn: ({ pageParam, signal }) =>
      read("/api/v1/connectors/github/{id}/repositories", {
        id: connectorId,
        query: { q: query, page: pageParam },
        signal,
      }),
    getNextPageParam: (last, pages) =>
      pages.length * last.page_size < last.total ? pages.length + 1 : undefined,
    enabled: !!connectorId && !disabled,
  });
  const items = [
    ...new Map(
      repos.data?.pages
        .flatMap((page) => page.items)
        .map((repo) => [repo.full_name, repo]),
    ).values(),
  ];
  const loading = repos.isFetching || search.trim() !== query;
  const options: { value: string; label: string; private?: boolean }[] =
    items.map((repo) => ({
      value: repo.full_name,
      label: repo.full_name,
      private: repo.private,
    }));
  if (value && !query && !options.some((option) => option.value === value))
    options.unshift({ value, label: value });
  return (
    <div className="field repository-select">
      <span id={id}>GitHub 仓库</span>
      <Select
        motion={false}
        aria-labelledby={id}
        aria-label="搜索并选择 GitHub 仓库"
        aria-describedby={`${id}-help`}
        prefix={<IconGithubLogo aria-hidden />}
        placeholder={
          connectorId
            ? "输入仓库名称搜索，如 owner/repository"
            : "请先选择 GitHub 连接"
        }
        filter
        remote
        showClear
        loading={loading}
        disabled={disabled || !connectorId}
        value={value || undefined}
        onChange={(next) => {
          onChange(String(next ?? ""));
          setSearch("");
        }}
        onSearch={setSearch}
        optionList={options}
        emptyContent={
          repos.error
            ? "仓库加载失败，请重试"
            : loading
              ? "正在搜索仓库…"
              : query
                ? "没有匹配的仓库"
                : "暂无可访问的仓库"
        }
        renderOptionItem={(option) => (
          <div
            key={option.value}
            role="option"
            aria-selected={option.selected}
            id={option.semiOptionId}
            style={option.style}
            className={`${option.className} repository-option ${option.focused ? "is-focused" : ""} ${option.selected ? "is-selected" : ""}`}
            onClick={option.onClick}
            onMouseEnter={option.onMouseEnter}
          >
            <IconGithubLogo aria-hidden />
            <span>{option.label}</span>
            <Tag size="small" color={option.private ? "orange" : "grey"}>
              {option.private === undefined
                ? "已选择"
                : option.private
                  ? "私有"
                  : "公开"}
            </Tag>
            {option.selected && <span aria-hidden>✓</span>}
          </div>
        )}
        outerBottomSlot={
          repos.hasNextPage || repos.error ? (
            <Space className="select-footer">
              <Button
                theme="borderless"
                loading={repos.isFetching}
                onClick={() =>
                  repos.error
                    ? void repos.refetch()
                    : void repos.fetchNextPage()
                }
              >
                {repos.error ? "重新加载" : "加载更多仓库"}
              </Button>
            </Space>
          ) : undefined
        }
        style={{ width: "100%" }}
      />
      <Typography.Text id={`${id}-help`} type="tertiary" size="small">
        {disabled
          ? "已保存的仓库"
          : loading && connectorId
            ? "正在搜索仓库…"
            : "搜索此连接可访问的仓库，选择后点击「验证并绑定」。"}
      </Typography.Text>
      <ErrorBox error={repos.error} />
    </div>
  );
}
