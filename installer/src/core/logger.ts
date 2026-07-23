import { mkdirSync, appendFileSync, existsSync, writeFileSync } from "fs";
import { join } from "path";

export type LogLevel = "debug" | "info" | "warn" | "error" | "success";

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  message: string;
  context?: string;
  data?: any;
}

const LEVEL_COLORS: Record<LogLevel, string> = {
  debug: "#6b7280",
  info: "#3b82f6",
  warn: "#eab308",
  error: "#ef4444",
  success: "#22c55e",
};

const LEVEL_ICONS: Record<LogLevel, string> = {
  debug: "·",
  info: "ℹ",
  warn: "⚠",
  error: "✗",
  success: "✓",
};

export class Logger {
  private logFile: string;
  private entries: LogEntry[] = [];
  private context: string;

  constructor(logDir: string, context: string = "installer") {
    this.context = context;
    mkdirSync(logDir, { recursive: true });
    const date = new Date().toISOString().split("T")[0];
    this.logFile = join(logDir, `installer-${date}.log`);
    if (!existsSync(this.logFile)) {
      writeFileSync(this.logFile, `# Installer Log — ${new Date().toISOString()}\n`);
    }
  }

  private write(level: LogLevel, message: string, data?: any) {
    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      message,
      context: this.context,
      data,
    };
    this.entries.push(entry);

    const line = `[${entry.timestamp}] [${level.toUpperCase()}] [${this.context}] ${message}`;
    appendFileSync(this.logFile, line + "\n");

    if (data) {
      appendFileSync(this.logFile, `  data: ${JSON.stringify(data)}\n`);
    }
  }

  debug(message: string, data?: any) {
    this.write("debug", message, data);
  }

  info(message: string, data?: any) {
    this.write("info", message, data);
  }

  warn(message: string, data?: any) {
    this.write("warn", message, data);
  }

  error(message: string, data?: any) {
    this.write("error", message, data);
  }

  success(message: string, data?: any) {
    this.write("success", message, data);
  }

  child(context: string): Logger {
    const child = new Logger(join(this.logFile, ".."), `${this.context}:${context}`);
    child.entries = this.entries;
    return child;
  }

  getEntries(): LogEntry[] {
    return [...this.entries];
  }

  getLogFile(): string {
    return this.logFile;
  }

  static formatTerminal(level: LogLevel, message: string, context?: string): string {
    const icon = LEVEL_ICONS[level];
    const color = LEVEL_COLORS[level];
    const ctx = context ? `\x1b[90m[${context}]\x1b[0m ` : "";
    return `\x1b[${color === "#6b7280" ? "90" : color === "#3b82f6" ? "34" : color === "#eab308" ? "33" : color === "#ef4444" ? "31" : "32"}m${icon}\x1b[0m ${ctx}${message}`;
  }
}

let globalLogger: Logger | null = null;

export function createLogger(logDir: string, context?: string): Logger {
  globalLogger = new Logger(logDir, context);
  return globalLogger;
}

export function getLogger(): Logger {
  if (!globalLogger) {
    globalLogger = new Logger("/tmp/installer-logs", "installer");
  }
  return globalLogger;
}
