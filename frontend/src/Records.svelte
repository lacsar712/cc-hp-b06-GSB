<script>
  export let api
  export let role

  let rows = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let error = ''
  let mergeCode = ''
  let activeFilter = ''

  async function load(code = '') {
    error = ''
    try {
      rows = await api(code ? `/api/batches?merge_code=${encodeURIComponent(code)}` : '/api/batches')
      activeFilter = code
    } catch (err) {
      error = err.message
    }
  }

  async function save() {
    error = ''
    try {
      await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          herb,
          steps: [{ name: '清炒', temp_c: Number(tempC), minutes: Number(minutes) }],
        }),
      })
      await load(activeFilter)
    } catch (err) {
      error = err.message
    }
  }

  function applyFilter() {
    load(mergeCode.trim())
  }

  function clearFilter() {
    mergeCode = ''
    load()
  }

  load()
</script>

{#if role === 'writer'}
  <section class="card">
    <h2>写入清炒记录</h2>
    <input bind:value={herb} placeholder="饮片" />
    <input type="number" bind:value={tempC} />
    <input type="number" bind:value={minutes} />
    <button on:click={save}>写入清炒记录</button>
  </section>
{/if}
{#if error}<p class="err">{error}</p>{/if}
<section class="card">
  <h2>记录总表</h2>
  <div class="filter">
    <input bind:value={mergeCode} placeholder="合并批号，如 HB-20260925-0001" />
    <button on:click={applyFilter}>按合并批号过滤</button>
    {#if activeFilter}
      <button on:click={clearFilter}>清除过滤</button>
      <span class="hint">当前过滤：{activeFilter}（服务端过滤）</span>
    {/if}
  </div>
  {#if rows.length === 0}
    <p class="empty">无匹配记录</p>
  {:else}
    <table>
      <thead>
        <tr><th>编号</th><th>饮片</th><th>结论</th><th>原因</th><th>清炒温度</th><th>合并批号</th></tr>
      </thead>
      <tbody>
        {#each rows as row}
          <tr>
            <td>#{row.id}</td>
            <td>{row.herb}</td>
            <td>{row.verdict}</td>
            <td>{row.reason}</td>
            <td>{row.doc.steps[0].temp_c}</td>
            <td>{row.merge_code || '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .card { border: 1px solid #e7d9c4; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
  h2 { font-size: 17px; color: #7c2d12; margin: 4px 0 10px; }
  input { margin-right: 8px; padding: 6px; }
  .filter { margin-bottom: 10px; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
  .filter input { width: 240px; }
  .hint { color: #92755c; font-size: 13px; }
  .empty { color: #92755c; }
  .err { color: #b91c1c; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #e7d9c4; padding: 6px 10px; text-align: left; font-size: 14px; }
  th { background: #faf3e8; }
</style>
