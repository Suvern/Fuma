import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import "./card-markdown.css";

/** Preview the common inline syntax supported by Feishu lark_md, without raw HTML. */
export function CardMarkdown({ children }: { children: string }) {
  return <div className="card-markdown">
    <Markdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      allowedElements={["p", "br", "strong", "em", "del", "a"]}
      unwrapDisallowed
      urlTransform={(url) => /^https?:\/\//i.test(url) ? url : ""}
      components={{ a: ({ href, children }) => href
        ? <a href={href} target="_blank" rel="noreferrer">{children}</a>
        : <span>{children}</span> }}
    >{children}</Markdown>
  </div>;
}
