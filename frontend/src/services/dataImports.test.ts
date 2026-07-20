import { afterEach, expect, it, vi } from "vitest";

import { inspectImport, previewImport } from "./dataImports";

afterEach(() => vi.unstubAllGlobals());

it("uploads the selected file as a raw controlled import", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        batch_id: "batch-1",
        provider_name: "local_csv",
        columns: ["symbol"],
        suggested_mapping: { symbol: "symbol" },
        row_count: 1,
        file_size: 5,
        source_file_hash: "a".repeat(64),
      }),
      { status: 201 },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  const file = new File(["hello"], "bars.csv", { type: "text/csv" });

  await inspectImport(file);

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/data/imports/inspect?filename=bars.csv",
    expect.objectContaining({ method: "POST", body: file }),
  );
});

it("sends explicit field mapping for preview", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
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
        sample_rows: [],
      }),
      { status: 200 },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);

  await previewImport("batch-1", { symbol: "symbol" });

  const request = fetchMock.mock.calls[0][1] as RequestInit;
  expect(JSON.parse(request.body as string)).toEqual({
    batch_id: "batch-1",
    field_mapping: { symbol: "symbol" },
  });
});
