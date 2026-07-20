export function NotFoundPage() {
  return (
    <main className="page-shell">
      <section className="state-panel state-panel--danger">
        <div>
          <p className="state-panel__label">404</p>
          <h1>页面不存在</h1>
          <p>请求的页面不存在，请返回系统状态页。</p>
          <a href="/">返回系统状态</a>
        </div>
      </section>
    </main>
  );
}
