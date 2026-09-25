<script>
  export let api
  export let role

  let candidates = []
  let merges = []
  let events = []
  let selected = []
  let error = ''
  let notice = ''

  async function loadAll() {
    error = ''
    try {
      const [rows, ms, evs] = await Promise.all([
        api('/api/batches'),
        api('/api/merge-batches'),
        api('/api/merge-events'),
      ])
      candidates = rows.filter((r) => r.verdict === '放行' && !r.merge_code)
      merges = ms
      events = evs
    } catch (err) {
      error = err.message
    }
  }

  async function pin() {
    error = ''
    notice = ''
    try {
      const merge = await api('/api/merge-batches', {
        method: 'POST',
        body: JSON.stringify({ batch_ids: selected }),
      })
      notice = `已钉成合并批 ${merge.code}`
      selected = []
      await loadAll()
    } catch (err) {
      error = err.message
    }
  }

  async function split(id) {
    error = ''
    notice = ''
    try {
      const merge = await api(`/api/merge-batches/${id}/split`, { method: 'POST' })
      notice = `合并批 ${merge.code} 已拆回`
      await loadAll()
    } catch (err) {
      error = err.message
    }
  }

  function fmt(t) {
    return t ? new Date(t).toLocaleString() : '—'
  }

  loadAll()
</script>

{#if role === 'writer'}
  <section class="card">
    <h2>钉批区</h2>
    <p class="hint">勾选至少两条放行且未入合并批的记录，钉成合并批并生成合并批号。</p>
    {#if candidates.length === 0}
      <p class="empty">暂无可钉的放行记录。</p>
    {:else}
      {#each candidates as row}
        <label class="pick">
          <input type="checkbox" bind:group={selected} value={row.id} />
          #{row.id} {row.herb} · {row.verdict} · {row.reason}
        </label>
      {/each}
      <button on:click={pin} disabled={selected.length < 2}>钉成合并批（已选 {selected.length} 条）</button>
    {/if}
  </section>
{/if}
{#if error}<p class="err">{error}</p>{/if}
{#if notice}<p class="ok">{notice}</p>{/if}

<section class="card">
  <h2>合并批详情</h2>
  {#if merges.length === 0}
    <p class="empty">暂无合并批。</p>
  {:else}
    {#each merges as m}
      <div class="merge">
        <h3>
          {m.code}
          <span class="tag" class:split={m.status !== 'active'}>
            {m.status === 'active' ? '生效中' : '已拆回'}
          </span>
        </h3>
        <p class="hint">
          由 {m.created_by} 于 {fmt(m.created_at)} 钉成
          {#if m.status === 'split'}；{m.split_by} 于 {fmt(m.split_at)} 拆回{/if}
        </p>
        <table>
          <thead>
            <tr><th>成员编号</th><th>饮片</th><th>结论</th><th>原因</th></tr>
          </thead>
          <tbody>
            {#each m.members as mem}
              <tr><td>#{mem.id}</td><td>{mem.herb}</td><td>{mem.verdict}</td><td>{mem.reason}</td></tr>
            {/each}
          </tbody>
        </table>
        {#if role === 'writer' && m.status === 'active'}
          <button class="danger" on:click={() => split(m.id)}>拆回</button>
        {/if}
      </div>
    {/each}
  {/if}
</section>

<section class="card">
  <h2>拆回履历</h2>
  {#if events.length === 0}
    <p class="empty">暂无履历。</p>
  {:else}
    <table>
      <thead>
        <tr><th>时间</th><th>操作</th><th>合并批号</th><th>成员编号</th><th>操作人</th></tr>
      </thead>
      <tbody>
        {#each events as e}
          <tr>
            <td>{fmt(e.at)}</td>
            <td>{e.action === 'merge' ? '钉成' : '拆回'}</td>
            <td>{e.code}</td>
            <td>{(e.detail.batch_ids || []).map((i) => '#' + i).join('、')}</td>
            <td>{e.actor}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .card { border: 1px solid #e7d9c4; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
  h2 { font-size: 17px; color: #7c2d12; margin: 4px 0 10px; }
  h3 { margin: 4px 0; color: #3f2f1f; }
  .merge { border-top: 1px dashed #e7d9c4; padding: 10px 0; }
  .merge:first-of-type { border-top: none; }
  .pick { display: block; margin: 6px 0; }
  .pick input { margin-right: 6px; }
  button { margin-top: 8px; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .danger { color: #b91c1c; }
  .hint { color: #92755c; font-size: 13px; margin: 4px 0 8px; }
  .empty { color: #92755c; }
  .err { color: #b91c1c; }
  .ok { color: #15803d; }
  .tag {
    font-size: 12px; background: #dcfce7; color: #15803d;
    border-radius: 10px; padding: 2px 10px; vertical-align: middle;
  }
  .tag.split { background: #fee2e2; color: #b91c1c; }
  table { border-collapse: collapse; width: 100%; margin-top: 6px; }
  th, td { border: 1px solid #e7d9c4; padding: 6px 10px; text-align: left; font-size: 14px; }
  th { background: #faf3e8; }
</style>
