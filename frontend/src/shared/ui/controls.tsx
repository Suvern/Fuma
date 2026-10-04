import { IconSearch } from "@douyinfe/semi-icons";
import type { ButtonProps } from "@douyinfe/semi-ui-19/lib/es/button";
import type { InputProps } from "@douyinfe/semi-ui-19/lib/es/input";
import {
  Children,
  isValidElement,
  useId,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import Banner from "@douyinfe/semi-ui-19/lib/es/banner";
import SemiButton from "@douyinfe/semi-ui-19/lib/es/button";
import Card from "@douyinfe/semi-ui-19/lib/es/card";
import Collapse from "@douyinfe/semi-ui-19/lib/es/collapse";
import SemiInput from "@douyinfe/semi-ui-19/lib/es/input";
import Tabs from "@douyinfe/semi-ui-19/lib/es/tabs";
import Tag from "@douyinfe/semi-ui-19/lib/es/tag";
import Typography from "@douyinfe/semi-ui-19/lib/es/typography";
import { Link, useLocation, useNavigate, type LinkProps } from "react-router";

/** Keep native form submission and validation while using Semi's controls. */
export function Button({
  type = "submit",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  const primary = className.split(" ").includes("primary");
  const danger = className.split(" ").includes("danger");
  return (
    <SemiButton
      {...(props as ButtonProps)}
      htmlType={type}
      type={danger ? "danger" : primary ? "primary" : "tertiary"}
      theme={primary ? "solid" : "light"}
      className={className}
    />
  );
}

export function Input({
  onChange,
  onInput,
  size,
  value,
  defaultValue,
  readOnly,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  void size;
  return (
    <SemiInput
      {...props}
      {...(value !== undefined ? { value: value as string | number } : {})}
      defaultValue={defaultValue as string | number | undefined}
      readonly={readOnly}
      prefix={props.type === "search" ? <IconSearch aria-hidden /> : undefined}
      mode={props.type === "password" ? "password" : undefined}
      onChange={(_, event) => onChange?.(event)}
      onInput={onInput as InputProps["onInput"]}
      validateStatus={props["aria-invalid"] ? "error" : "default"}
    />
  );
}

export function Panel({
  children,
  className = "",
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <section
      {...props}
      className={`panel ${className.replace(/\bpanel\b/g, "")}`}
    >
      <Card>{children}</Card>
    </section>
  );
}

export function CardLink({ children, className = "", ...props }: LinkProps) {
  return (
    <Link
      {...props}
      className={`card-link ${className.replace(/\bpanel\b/g, "")}`}
    >
      <Card>{children}</Card>
    </Link>
  );
}

export function Notice({
  children,
  className = "",
  role = "status",
}: {
  children: ReactNode;
  className?: string;
  role?: string;
}) {
  return (
    <div role={role === "alert" ? undefined : role} className="feedback">
      <Banner
        fullMode={false}
        type={
          className.includes("error")
            ? "danger"
            : className.includes("success")
              ? "success"
              : "info"
        }
        closeIcon={null}
        description={children}
      />
    </div>
  );
}

export function Badge({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <Tag
      color={
        className.includes("fail")
          ? "red"
          : className.includes("pass")
            ? "green"
            : "grey"
      }
      shape="square"
    >
      {children}
    </Tag>
  );
}

export function Disclosure({
  title,
  children,
  className,
}: {
  title: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <Collapse className={className} keepDOM>
      <Collapse.Panel header={title} itemKey={id}>
        {children}
      </Collapse.Panel>
    </Collapse>
  );
}

export function PageTabs({
  children,
}: {
  children?: ReactNode;
  className?: string;
}) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const appPath = pathname.match(/^\/admin\/apps\/[^/]+/)?.[0];
  const items = appPath
    ? [
        { to: appPath, label: "应用设置" },
        { to: `${appPath}/packages`, label: "安装包" },
        { to: `${appPath}/versions`, label: "版本发布" },
        { to: `${appPath}/releases`, label: "GitHub Releases" },
        { to: `${appPath}/debug`, label: "Debug 包" },
        { to: `${appPath}/actions`, label: "Actions 规则" },
        { to: `${appPath}/events`, label: "构建事件" },
      ]
    : Children.toArray(children).flatMap((child) =>
        isValidElement<LinkProps>(child)
          ? [{ to: String(child.props.to), label: child.props.children }]
          : [],
      );
  return (
    <Tabs
      className="page-tabs"
      type="line"
      tabBarStyle={{ whiteSpace: "nowrap", overflowX: "auto" }}
      activeKey={pathname}
      onChange={navigate}
    >
      {items.map((item) => (
        <Tabs.TabPane key={item.to} itemKey={item.to} tab={item.label} />
      ))}
    </Tabs>
  );
}

export function Metric({
  title,
  value,
  suffix,
}: {
  title: string;
  value: ReactNode;
  suffix?: string;
}) {
  return (
    <div className="metric">
      <Typography.Text type="tertiary">{title}</Typography.Text>
      <Typography.Title heading={3}>
        {value}
        {suffix && (
          <Typography.Text type="tertiary" size="small">
            {" "}
            {suffix}
          </Typography.Text>
        )}
      </Typography.Title>
    </div>
  );
}
