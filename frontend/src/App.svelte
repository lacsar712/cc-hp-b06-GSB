<script>
  import { onMount } from 'svelte'

  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let displayName = localStorage.getItem('herb_user') || ''

  let route = parseHash()
  let rows = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let error = ''

  let mergeFilter = route.query.merge_no || ''
  let merges = []
  let ledger = []
  let candidates = []
  let picked = new Set()

  function parseHash() {
    const raw = location.hash.replace(/^#/, '') || '/'
    const [path, queryString] = raw.split('?')
    return { path: path || '/', query: new URLSearchParams(queryString || '') }
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || '请求失败')
    return data
  }

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    token = data.access_token
    role = data.role
    displayName = data.username
    localStorage.setItem('herb_token', token)
    localStorage.setItem('herb_role', role)
    localStorage.setItem('herb_user', displayName)
    await refresh()
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
    displayName = ''
  }

  $: isWriter = role === 'writer'

  async function loadBatches() {
    const q = route.query.get('merge_no')
    mergeFilter = q || ''
    rows = await api(q ? `/api/batches?merge_no=${encodeURIComponent(q)}` : '/api/batches')
  }

  async function loadMerges() {
    const [mergeList, ledgerList, allRows] = await Promise.all([
      api('/api/merges'),
      api('/api/merges/ledger/all'),
      api('/api/batches'),
    ])
    merges = mergeList
    ledger = ledgerList
    const activeNos = new Set(merges.filter((m) => !m.unmerged_at).map((m) => m.merge_no))
    candidates = allRows.filter((r) => r.verdict === '放行' && !(r.merge_no && activeNos.has(r.merge_no)))
    picked = new Set([...picked].filter((id) => candidates.some((c) => c.id === id)))
  }

  async function refresh() {
    error = ''
    try {
      if (route.path === '/merges') {
        await loadMerges()
      } else {
        await loadBatches()
      }
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
      await loadBatches()
    } catch (err) {
      error = err.message
    }
  }

  function applyFilter() {
    const v = mergeFilter.trim()
    location.hash = v ? `/?merge_no=${encodeURIComponent(v)}` : '/'
  }

  function clearFilter() {
    location.hash = '/'
  }

  function togglePick(id) {
    if (picked.has(id)) picked.delete(id)
    else picked.add(id)
    picked = picked
  }

  async function pin() {
    error = ''
    const ids = [...picked]
    if (ids.length < 2) {
      error = '至少钉两个放行行'
      return
    }
    try {
      await api('/api/merges', { method: 'POST', body: JSON.stringify({ batch_ids: ids }) })
      picked = new Set()
      await loadMerges()
    } catch (err) {
      error = err.message
    }
  }

  async function unpin(mergeNo) {
    error = ''
    try {
      await api('/api/merges/unmerge', { method: 'POST', body: JSON.stringify({ merge_no: mergeNo }) })
      await loadMerges()
    } catch (err) {
      error = err.message
    }
  }

  function fmt(ts) {
    return ts ? new Date(ts).toLocaleString('zh-CN', { hour12: false }) : ''
  }

  onMount(() => {
    window.addEventListener('hashchange', async () => {
      route = parseHash()
      await refresh()
    })
    if (token) refresh()
  })
</script>

<main>
  {#if !token}
    <h1>饮片炮制记录台</h1>
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav class="topbar">
      <a class="brand" href="#/">饮片炮制记录台</a>
      <a href="#/" class:on={route.path === '/'}>总表</a>
      <a href="#/merges" class:on={route.path === '/merges'}>批次合并</a>
      <span class="spacer"></span>
      <span class="who">{displayName}（{isWriter ? '炮制员' : '质检员'}）</span>
      <button on:click={leave}>退出</button>
    </nav>

    {#if error}<p class="error">{error}</p>{/if}

    {#if route.path === '/merges'}
      <section>
        <h2>钉批区</h2>
        {#if isWriter}
          <p>勾选若干已放行行，钉成一个合并批。</p>
          <ul class="cands">
            {#each candidates as c}
              <li>
                <label>
                  <input type="checkbox" checked={picked.has(c.id)} on:change={() => togglePick(c.id)} />
                  #{c.id} {c.herb} · {c.verdict}
                </label>
              </li>
            {:else}
              <li class="muted">暂无可钉的放行行</li>
            {/each}
          </ul>
          <button on:click={pin} disabled={picked.size < 2}>钉成合并批（已选 {picked.size}）</button>
        {:else}
          <p class="muted">质检员可查看合并批与履历，钉批仅炮制员可操作。</p>
        {/if}
      </section>

      <section>
        <h2>合并批详情</h2>
        <ul class="merges">
          {#each merges as m}
            <li class:done={!!m.unmerged_at}>
              <div class="mhead">
                <strong>{m.merge_no}</strong>
                <span class="tag">{m.unmerged_at ? '已拆回' : '有效'}</span>
                <span class="muted">{m.created_by} 钉于 {fmt(m.created_at)}</span>
                {#if m.unmerged_at}
                  <span class="muted">{m.unmerged_by} 拆于 {fmt(m.unmerged_at)}</span>
                {/if}
                <span class="spacer"></span>
                <a href="#/?merge_no={encodeURIComponent(m.merge_no)}">按批号过滤总表</a>
                {#if isWriter && !m.unmerged_at}
                  <button on:click={() => unpin(m.merge_no)}>拆回</button>
                {/if}
              </div>
              <ul class="members">
                {#each m.members as mem}
                  <li><span class="bid">#{mem.id}</span> {mem.herb} · 结论：{mem.verdict}</li>
                {/each}
              </ul>
            </li>
          {:else}
            <li class="muted">尚无合并批</li>
          {/each}
        </ul>
      </section>

      <section>
        <h2>拆回履历</h2>
        <ul class="ledger">
          {#each ledger as e}
            <li>
              <span class="act" class:unpin={e.action === '拆回'}>{e.action}</span>
              <strong>{e.merge_no}</strong>
              {e.operator} · {fmt(e.created_at)} · {e.note}
            </li>
          {:else}
            <li class="muted">履历为空</li>
          {/each}
        </ul>
      </section>
    {:else}
      {#if isWriter}
        <section>
          <input bind:value={herb} placeholder="饮片" />
          <input type="number" bind:value={tempC} />
          <input type="number" bind:value={minutes} />
          <button on:click={save}>写入清炒记录</button>
        </section>
      {/if}

      <section>
        <h2>总表</h2>
        <div class="filter">
          <input bind:value={mergeFilter} placeholder="按合并批号过滤（服务端）" />
          <button on:click={applyFilter}>过滤</button>
          {#if route.query.get('merge_no')}
            <button on:click={clearFilter}>清除筛选</button>
          {/if}
        </div>
        {#if route.query.get('merge_no')}
          <p class="muted">服务端过滤：合并批号 {route.query.get('merge_no')}</p>
        {/if}
        <table>
          <thead>
            <tr><th>编号</th><th>饮片</th><th>结论</th><th>原因</th><th>温度</th><th>合并批号</th></tr>
          </thead>
          <tbody>
            {#each rows as row}
              <tr class:pass={row.verdict === '放行'}>
                <td>#{row.id}</td>
                <td>{row.herb}</td>
                <td>{row.verdict}</td>
                <td>{row.reason}</td>
                <td>{row.doc.steps[0].temp_c}</td>
                <td>{row.merge_no || ''}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        {#if rows.length === 0}<p class="muted">没有匹配的行。</p>{/if}
      </section>
    {/if}
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 860px; margin: 24px auto; color: #3f2f1f; padding: 0 16px; }
  h1 { color: #7c2d12; }
  h2 { color: #7c2d12; font-size: 18px; margin-top: 28px; }
  input { margin-right: 8px; padding: 6px; }
  .topbar { display: flex; align-items: center; gap: 16px; border-bottom: 2px solid #d6c3ad; padding-bottom: 10px; }
  .topbar a { color: #7c2d12; text-decoration: none; }
  .topbar a.on { font-weight: bold; text-decoration: underline; }
  .brand { font-weight: bold; font-size: 18px; }
  .spacer { flex: 1; }
  .who { color: #6b5a48; font-size: 13px; }
  .error { color: #b91c1c; }
  .muted { color: #8a7a68; }
  .filter { margin: 10px 0; }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; }
  th, td { border: 1px solid #d6c3ad; padding: 6px 10px; text-align: left; }
  tr.pass td:nth-child(3) { color: #15803d; font-weight: bold; }
  ul { list-style: none; padding-left: 0; }
  .cands li, .merges li, .ledger li { padding: 6px 0; }
  .merges > li { border: 1px solid #d6c3ad; border-radius: 6px; padding: 10px 12px; margin-bottom: 10px; }
  .merges > li.done { background: #f5efe8; }
  .mhead { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .members { margin: 8px 0 0; padding-left: 8px; color: #5a4a38; }
  .bid { font-weight: bold; color: #7c2d12; }
  .tag { background: #7c2d12; color: #fff; border-radius: 4px; padding: 1px 8px; font-size: 12px; }
  .done .tag { background: #8a7a68; }
  .act { display: inline-block; min-width: 36px; text-align: center; border-radius: 4px; padding: 1px 8px; font-size: 12px; background: #15803d; color: #fff; margin-right: 6px; }
  .act.unpin { background: #b91c1c; }
  button { cursor: pointer; padding: 5px 12px; }
  button:disabled { cursor: not-allowed; opacity: 0.5; }
</style>
