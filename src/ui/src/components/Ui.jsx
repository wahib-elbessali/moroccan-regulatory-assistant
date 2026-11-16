import { Activity } from "lucide-react";
import { statusNames } from "../app/data.js";

export function Button({ children, className = "", variant = "primary", ...props }) {
  const styles = variant === "primary"
    ? "bg-[#245c48] text-white hover:bg-[#193e33]"
    : variant === "quiet"
      ? "text-[#596157] hover:bg-[#efefe8]"
      : variant === "danger"
        ? "bg-[#a54132] text-white hover:bg-[#873327]"
        : "border border-[#dedfd5] bg-white text-[#343a33] hover:bg-[#f7f7f2]";
  return <button className={`focus-ring inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold transition-colors ${styles} ${className}`} {...props}>{children}</button>;
}

export function Field({ label, className = "", ...props }) {
  return <label className={`grid gap-1.5 text-sm font-semibold text-[#434a40] ${className}`}>
    {label}<input className="focus-ring h-11 w-full rounded-md border border-[#dedfd5] bg-white px-3 font-normal text-[#242a24] placeholder:text-[#9b9d92]" {...props} />
  </label>;
}

export function StatusPill({ status, lang }) {
  const style = status === "ready" ? "bg-[#e6f1e8] text-[#356448]" : status === "failed" ? "bg-[#f8e9e5] text-[#a54132]" : "bg-[#f3eddf] text-[#896a34]";
  return <span className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-semibold ${style}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{statusNames[status]?.[lang] || status}</span>;
}

export function PageHeading({ eyebrow, title, intro }) {
  return <div><p className="text-[10px] font-bold uppercase tracking-[.14em] text-[#b76940]">{eyebrow}</p><h1 className="mt-2 text-3xl font-semibold text-[#28362b]">{title}</h1><p className="mt-2 text-sm text-[#777b70]">{intro}</p></div>;
}

export function Metric({ icon: Icon, label, value }) {
  return <div className="bg-[#fbfaf6] p-5"><div className="flex items-center justify-between"><span className="text-xs font-semibold text-[#777b70]">{label}</span><Icon size={17} className="text-[#81917d]" /></div><div className="mt-4 text-3xl font-semibold text-[#29392d]">{value}</div></div>;
}

export function BusyIcon() { return <Activity size={17} className="animate-pulse" />; }