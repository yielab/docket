# Troubleshooting Guide

## Extension Says "No Tab Connected" / Work Doesn't Persist

### Síntomas
- Extensión de OpenClaw está activa (icono visible)
- Error: "Chrome extension relay is running, but no tab is connected"
- El agente dice que no puede usar el browser
- El trabajo no se mantiene en la misma tab
- Cada vez tienes que re-conectar manualmente

### Causa Raíz
La extensión de OpenClaw requiere **attachment manual** a una tab. Este attachment:
- NO persiste después de reiniciar el browser
- NO persiste después de cerrar la tab
- Requiere click manual en el icono de la extensión

### Solución - Conectar la Extensión

**Paso 1: Abrir Brave**
```bash
# El browser debe estar corriendo
ps aux | grep "openclaw/browser" | grep -v grep
```

Si no hay procesos, OpenClaw auto-iniciará cuando sea necesario.

**Paso 2: Crear/Abrir una Tab de Trabajo**

Abre una tab nueva en Brave y navega a cualquier sitio (o déjala en `about:blank`).

**Paso 3: Click en el Icono de la Extensión**

1. Busca el icono de **OpenClaw Browser Relay** en la barra de extensiones de Brave (esquina superior derecha)
2. Si no lo ves, click en el ícono de extensiones (puzzle piece) y pin la extensión
3. **Click en el icono de OpenClaw** en la tab que quieres usar
4. El icono debe cambiar de color o mostrar "Connected" / "Attached"

**Paso 4: Verificar Conexión**

```bash
# Ver los logs - debe mostrar "tab attached" o similar
tail -f /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep -i "attach\|tab\|extension"
```

### Automatizar la Conexión (Workaround)

Actualmente NO hay forma de auto-conectar la extensión. Debes:

**Opción 1: Usar Siempre la Misma Tab**
- No cierres la tab conectada
- Manténla abierta todo el tiempo
- Pin la tab para evitar cerrarla accidentalmente

**Opción 2: Crear Recordatorio Visual**

Agregar un sticky note o recordatorio en tu pantalla:
```
🔴 ANTES de pedirle a OpenClaw usar el browser:
   1. Abrir Brave
   2. Click icono extensión OpenClaw en una tab
   3. Verificar que dice "Connected"
```

**Opción 3: Macro/Script de Inicio**

Si usas Brave regularmente, crea un script de inicio:
```bash
#!/bin/bash
# ~/bin/openclaw-browser-setup.sh

# Esperar a que browser inicie
sleep 3

# Abrir URL de control de extensión
xdg-open "chrome-extension://pdkcmllnedlggdbgnopojdcelanfkaag/options.html"

echo "✓ Extensión OpenClaw abierta"
echo "🔴 ACCIÓN REQUERIDA: Click en el icono de la extensión en una tab para conectarla"
```

### Verificar Estado de la Extensión

```bash
# Ver si la extensión está cargada
grep -i "extension.*openclaw\|relay.*running" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -5

# Si ves "no tab is connected", necesitas clickear el icono
```

### Por Qué Es Así

Este diseño es **intencional** por razones de seguridad:
- Evita que la extensión controle tabs automáticamente sin permiso
- Te da control de qué tab específica usar
- Previene acceso no autorizado a tabs sensibles

**PERO** el trade-off es que debes re-conectar después de:
- Reinicio del browser
- Reinicio del gateway OpenClaw
- Cerrar la tab conectada

### Pedirle a OpenClaw Mejorar Esto

Si quieres que OpenClaw implemente auto-reconnect, considera:
1. Abrir un issue en el repo de OpenClaw
2. Sugerir opciones de "remember last tab" o "auto-attach on startup"
3. Mientras tanto, usa las workarounds arriba

## Brave Browser Disconnects Constantly

### Síntomas
- OpenClaw se desconecta frecuentemente en Brave
- El trabajo no se mantiene en la misma tab
- Browser muestra "Aw, Snap!" o errores de memoria
- Respuestas lentas o timeouts

### Causa Raíz
Procesos de Brave browser se acumulan durante días/semanas y consumen memoria excesiva (3+ GB). Los procesos viejos causan:
- Memory leaks
- Sesiones perdidas
- Tabs que no persisten
- WebSocket disconnections

### Solución Inmediata

**1. Reiniciar procesos de Brave:**
```bash
# Matar todos los procesos viejos de OpenClaw Brave
ps aux | grep "openclaw/browser" | grep -v grep | awk '{print $2}' | xargs -r kill -9

# Reiniciar gateway para que auto-inicie browser limpio
systemctl --user restart openclaw-gateway.service
```

**2. Verificar que funcionó:**
```bash
# Revisar que no hay procesos viejos
ps aux | grep "openclaw/browser" | grep -v grep

# Debe mostrar solo procesos nuevos (minutos u horas, no días)
```

### Solución Preventiva

**Opción A: Reinicio Manual Semanal**

Agregar a tu rutina semanal (recomendado lunes):
```bash
# Limpiar browser + reiniciar gateway
ps aux | grep "openclaw/browser" | grep -v grep | awk '{print $2}' | xargs -r kill -9
systemctl --user restart openclaw-gateway.service
```

**Opción B: Cron Job Automático**

Crear reinicio automático cada domingo a las 3am:
```bash
# Agregar al crontab del usuario
crontab -e

# Agregar esta línea:
0 3 * * 0 ps aux | grep "openclaw/browser" | grep -v grep | awk '{print \$2}' | xargs -r kill -9 && systemctl --user restart openclaw-gateway.service
```

**Opción C: Systemd Timer (más robusto)**

Crear timer systemd para reinicio automático:
```bash
# Crear service file
cat > ~/.config/systemd/user/openclaw-browser-restart.service <<'EOF'
[Unit]
Description=OpenClaw Browser Restart
After=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'ps aux | grep "openclaw/browser" | grep -v grep | awk "{print \$2}" | xargs -r kill -9'
ExecStartPost=/bin/systemctl --user restart openclaw-gateway.service
EOF

# Crear timer file (ejecuta cada 3 días)
cat > ~/.config/systemd/user/openclaw-browser-restart.timer <<'EOF'
[Unit]
Description=OpenClaw Browser Restart Timer

[Timer]
OnCalendar=daily
Persistent=true
Unit=openclaw-browser-restart.service

[Install]
WantedBy=timers.target
EOF

# Habilitar y arrancar timer
systemctl --user daemon-reload
systemctl --user enable openclaw-browser-restart.timer
systemctl --user start openclaw-browser-restart.timer

# Verificar estado
systemctl --user status openclaw-browser-restart.timer
```

### Verificar Estado de Browser

**Ver procesos actuales:**
```bash
ps -eo pid,etimes,cmd | grep "openclaw/browser" | grep -v grep | awk '{print "PID " $1 ": " int($2/86400) "d " int(($2%86400)/3600) "h " int(($2%3600)/60) "m"}'
```

**Ver uso de memoria:**
```bash
ps aux | grep "openclaw/browser" | grep -v grep | awk '{sum+=$6} END {print "Total: " sum/1024 " MB"}'
```

### Síntomas de Procesos Muy Viejos

Si ves procesos de **más de 3 días**, reinicia inmediatamente:
- ✅ Normal: procesos de horas o 1-2 días
- ⚠️ Cuidado: procesos de 3-5 días
- 🔴 Crítico: procesos de 6+ días (reinicia YA)

### Configuración de OpenClaw

**Verificar configuración de Telegram:**
```bash
openclaw config get channels.telegram
```

Debe mostrar:
```json
{
  "enabled": true,
  "streaming": "off",
  "groupPolicy": "allowlist"
}
```

**Nota:** `streaming: "off"` es correcto - OpenClaw usa polling por defecto que es más estable.

### Problemas de Sesión / Tabs

Si el trabajo no persiste en la misma tab:

**1. Limpiar cache de browser:**
```bash
rm -rf ~/.openclaw/browser/openclaw/user-data/Default/Cache/*
rm -rf ~/.openclaw/browser/openclaw/user-data/Default/"Code Cache"/*
rm -rf ~/.openclaw/browser/openclaw/user-data/Default/"Service Worker"/*

# Limpiar sesiones corruptas
rm -f ~/.openclaw/browser/openclaw/user-data/Default/"Current Session"
rm -f ~/.openclaw/browser/openclaw/user-data/Default/"Current Tabs"

# Reiniciar gateway
systemctl --user restart openclaw-gateway.service
```

**2. Verificar que no hay cookies bloqueadas:**

En Brave, verificar configuración:
- Settings → Privacy and Security → Cookies
- Asegurarse que `localhost` y `127.0.0.1` NO estén bloqueados
- Permitir cookies de terceros para OpenClaw

### Monitoreo de Desconexiones

**Ver eventos de desconexión en logs:**
```bash
grep -i "disconnect\|timeout\|connection.*closed" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | wc -l
```

Si ves **más de 10 desconexiones en un día**, reinicia el browser inmediatamente.

### Recursos Adicionales

**Logs importantes:**
- Gateway: `journalctl --user -u openclaw-gateway.service -f`
- OpenClaw: `/tmp/openclaw/openclaw-$(date +%Y-%m-%d).log`
- Browser stderr: `/tmp/openclaw/browser-*.log` (si existe)

**Comandos útiles:**
```bash
# Estado completo del sistema
systemctl --user status openclaw-gateway.service

# Logs en tiempo real
tail -f /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log

# Ver todas las conexiones activas
ss -tunlp | grep 18800
```

## Otros Problemas Comunes

### Gateway No Inicia
```bash
systemctl --user status openclaw-gateway.service
openclaw doctor --fix
```

### Agents No Responden
```bash
# Verificar que agent está registrado
openclaw agents list

# Re-registrar si falta
rack repair <agent-id>
```

### Telegram No Responde
```bash
# Verificar binding
openclaw bindings list

# Verificar grupo en allowlist
openclaw config get channels.telegram.groups

# Agregar grupo si falta
openclaw config set "channels.telegram.groups.-123456789" '{"requireMention": false}'
```

### Token Limits / Rate Limiting
```bash
# Ver uso actual
rack cost

# Cambiar a modelo más económico
rack profile <agent-id> economy
```
