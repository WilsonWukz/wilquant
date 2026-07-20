import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import * as importApi from "../services/dataImports";
import { DataImportPage } from "./DataImportPage";

afterEach(() => cleanup());

it("inspects and previews a local file without publish controls", async () => {
  vi.spyOn(importApi, "inspectImport").mockResolvedValue({
    batch_id: "batch-1",
    provider_name: "local_csv",
    columns: ["symbol", "exchange", "trade_date", "open", "high", "low", "close", "volume", "amount"],
    suggested_mapping: {
      symbol: "symbol",
      exchange: "exchange",
      trade_date: "trade_date",
      open: "open",
      high: "high",
      low: "low",
      close: "close",
      volume: "volume",
      amount: "amount",
    },
    row_count: 1,
    file_size: 100,
    source_file_hash: "a".repeat(64),
  });
  vi.spyOn(importApi, "previewImport").mockResolvedValue({
    batch_id: "batch-1",
    provider_name: "local_csv",
    source_name: "bars.csv",
    source_file_hash: "a".repeat(64),
    status: "PREVIEW_READY",
    row_count: 1,
    accepted_count: 1,
    rejected_count: 0,
    warning_count: 0,
    error_category: null,
    error_summary: null,
    sample_rows: [{ instrument_id: "600000.XSHG", trade_date: "2026-07-17" }],
  });
  vi.spyOn(importApi, "fetchImportIssues").mockResolvedValue({ items: [] });
  render(<DataImportPage />);
  const input = screen.getByLabelText("选择 CSV 或 Parquet 文件");
  fireEvent.change(input, { target: { files: [new File(["data"], "bars.csv")] } });

  fireEvent.click(screen.getByRole("button", { name: "检查文件" }));
  expect(await screen.findByText("字段映射")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "生成预览" }));

  expect(await screen.findByText("600000.XSHG")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /发布|交易|回测/ })).not.toBeInTheDocument();
});

it("shows a safe error when inspection fails", async () => {
  vi.spyOn(importApi, "inspectImport").mockRejectedValue(new Error("hidden detail"));
  render(<DataImportPage />);
  fireEvent.change(screen.getByLabelText("选择 CSV 或 Parquet 文件"), {
    target: { files: [new File(["data"], "bars.csv")] },
  });

  fireEvent.click(screen.getByRole("button", { name: "检查文件" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("导入请求失败");
  expect(screen.queryByText("hidden detail")).not.toBeInTheDocument();
});

it("marks fatal quality issues as dangerous", async () => {
  vi.spyOn(importApi, "inspectImport").mockResolvedValue({
    batch_id: "batch-fatal",
    provider_name: "local_csv",
    columns: ["symbol"],
    suggested_mapping: { symbol: "symbol" },
    row_count: 0,
    file_size: 10,
    source_file_hash: "b".repeat(64),
  });
  vi.spyOn(importApi, "previewImport").mockResolvedValue({
    batch_id: "batch-fatal",
    provider_name: "local_csv",
    source_name: "empty.csv",
    source_file_hash: "b".repeat(64),
    status: "PREVIEW_READY",
    row_count: 0,
    accepted_count: 0,
    rejected_count: 0,
    warning_count: 0,
    error_category: null,
    error_summary: null,
    sample_rows: [],
  });
  vi.spyOn(importApi, "fetchImportIssues").mockResolvedValue({
    items: [
      {
        row_number: null,
        symbol: null,
        field_name: null,
        severity: "FATAL",
        issue_code: "EMPTY_FILE",
        message: "文件没有数据行",
        raw_value: null,
      },
    ],
  });
  render(<DataImportPage />);
  fireEvent.change(screen.getByLabelText("选择 CSV 或 Parquet 文件"), {
    target: { files: [new File([""], "empty.csv")] },
  });
  fireEvent.click(screen.getByRole("button", { name: "检查文件" }));
  await screen.findByText("字段映射");
  fireEvent.click(screen.getByRole("button", { name: "生成预览" }));

  expect(
    await screen.findByText(
      (_, element) =>
        element?.tagName === "LI" && element.textContent?.includes("文件没有数据行") === true,
    ),
  ).toHaveClass("issue--danger");
});
