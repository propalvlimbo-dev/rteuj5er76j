package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Timer.B: баланс движений по Grim Timer.
 * Каждое движение +50 мс кредита, пол — пинг + 150 мс (пинг режем
 * на 1000 — Grim TimerLimit). Флаг за 3 подряд выхода за now + 100:
 * джиттер и догоняющие тики дают 1-2, таймер-чит — серию.
 * Портировано из Grim (GPL-3.0), адаптировано под главный поток.
 */
public final class TimerB extends Check {

    private final Map<UUID, Long> balance = new ConcurrentHashMap<>();
    private final Map<UUID, Integer> excess = new ConcurrentHashMap<>();

    public TimerB(ElytrixFuckCheats plugin) {
        super(plugin, "Timer", "B", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        balance.remove(uuid);
        excess.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        UUID id = player.getUniqueId();
        long now = System.nanoTime();
        long bal = balance.getOrDefault(id, now);
        bal += 50_000_000L;
        long pingMs = 0;
        try {
            int ping = plugin.getPacketManager().ping(player);
            if (ping > 0) {
                pingMs = Math.min(ping, 1000);
            }
        } catch (Throwable ignored) {
        }
        long floor = now - (pingMs + 150) * 1_000_000L;
        if (bal < floor) {
            bal = floor;
        }
        if (bal > now + 100_000_000L) {
            int count = excess.getOrDefault(id, 0) + 1;
            excess.put(id, count);
            balance.put(id, now + 100_000_000L);
            if (count >= 3) {
                excess.remove(id);
                flag(plugin.getDataManager().get(player), "timer balance");
            }
            return;
        }
        excess.remove(id);
        balance.put(id, bal);
    }
}
