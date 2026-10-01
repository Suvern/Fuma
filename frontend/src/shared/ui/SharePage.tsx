import { useEffect, useState } from "react";
import QRCode from "qrcode";

/** Only pass the permanent page URL. Download bearer URLs must never be shared here. */
export function SharePage({ url }: { url: string }) {
  const [qr, setQr] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    let current = true;
    void QRCode.toString(url, {
      type: "svg",
      width: 180,
      margin: 2,
      errorCorrectionLevel: "M",
    }).then(
      (svg) => {
        if (current)
          setQr(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
      },
      () => {
        if (current) setMessage("二维码暂不可用，请复制页面链接。");
      },
    );
    return () => {
      current = false;
    };
  }, [url]);
  return (
    <details className="share-page">
      <summary>分享固定分发页面</summary>
      <p className="muted">
        访问此页面仍需飞书验证，二维码不包含临时下载凭据。
      </p>
      {qr && <img src={qr} width={180} height={180} alt="固定分发页面二维码" />}
      <input aria-label="固定页面地址" readOnly value={url} />
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard.writeText(url).then(
            () => setMessage("已复制固定页面链接。"),
            () => setMessage("请在地址框中手动复制链接。"),
          );
        }}
      >
        复制页面链接
      </button>
      {message && <p role="status">{message}</p>}
    </details>
  );
}
