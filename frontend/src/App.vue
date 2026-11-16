<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand-block">
        <div class="brand-seal" aria-hidden="true">证</div>
        <div class="brand-text">
          <span class="brand-cn">核证匣</span>
          <span class="brand-sub">举证放行闭环</span>
        </div>
      </div>
      <nav class="nav">
        <router-link to="/">总览</router-link>
        <router-link to="/subjects">举证对象</router-link>
        <router-link to="/sample">采样台</router-link>
        <router-link to="/packs">证据包</router-link>
        <router-link to="/checklist">校验清单</router-link>
        <router-link to="/release">放行台</router-link>
        <router-link to="/settings">设置</router-link>
      </nav>
    </header>
    <div class="teal-strip" aria-hidden="true"></div>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>
