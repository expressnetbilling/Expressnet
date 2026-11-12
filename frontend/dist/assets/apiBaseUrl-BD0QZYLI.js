const r="/api";function e(i="expressnetbilling.com/api"){const t=String(i||"").trim().replace(/\/+$/,"");return t&&(t.startsWith("/")||/^https?:\/\//i.test(t))?t:r}export{e as a};
