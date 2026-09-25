<script>
  import { onMount } from 'svelte'
  import Records from './Records.svelte'
  import Merge from './Merge.svelte'

  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let view = location.hash === '#/merge' ? 'merge' : 'records'
  let error = ''

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
    error = ''
    try {
      const data = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      token = data.access_token
      role = data.role
      localStorage.setItem('herb_token', token)
      localStorage.setItem('herb_role', role)
    } catch (err) {
      error = err.message
    }
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
  }

  onMount(() => {
    const onHash = () => {
      view = location.hash === '#/merge' ? 'merge' : 'records'
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  })
</script>

<main>
  <h1>饮片炮制记录台</h1>
  {#if !token}
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    {#if error}<p class="err">{error}</p>{/if}
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav class="topbar">
      <a href="#/" class:active={view === 'records'}>记录总表</a>
      <a href="#/merge" class:active={view === 'merge'}>批次合并</a>
      <span class="who">{role === 'writer' ? '炮制员' : '质检员'}</span>
      <button on:click={leave}>退出</button>
    </nav>
    {#if view === 'records'}
      <Records {api} {role} />
    {:else}
      <Merge {api} {role} />
    {/if}
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 860px; margin: 24px auto; color: #3f2f1f; }
  h1 { color: #7c2d12; }
  input { margin-right: 8px; padding: 6px; }
  .topbar {
    display: flex; align-items: center; gap: 16px;
    border-bottom: 2px solid #e7d9c4; padding-bottom: 10px; margin-bottom: 16px;
  }
  .topbar a { color: #7c2d12; text-decoration: none; padding: 4px 10px; border-radius: 6px; }
  .topbar a.active { background: #7c2d12; color: #fff7ed; }
  .topbar .who { margin-left: auto; color: #92755c; }
  .err { color: #b91c1c; }
</style>
