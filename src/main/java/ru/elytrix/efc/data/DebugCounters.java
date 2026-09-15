package ru.elytrix.efc.data;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerAnimationEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Счётчики событий для /efc debug: показывают, какие сигналы вообще
 * долетают от игрока (движение, удары, взмахи, клики + пакетные
 * взмахи/удары, если активен пакетный слой). Почти бесплатные.
 */
public final class DebugCounters implements Listener {

    // 0 — движение, 1 — удары, 2 — взмахи, 3 — клики в воздух,
    // 4 — пакетные взмахи, 5 — пакетные удары.
    private final Map<UUID, long[]> counts = new ConcurrentHashMap<>();

    public DebugCounters(ElytrixFuckCheats plugin) {
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        bump(event.getPlayer().getUniqueId(), 0);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (DamageUtil.damagerOf(event) instanceof Player) {
            bump(((Player) DamageUtil.damagerOf(event)).getUniqueId(), 1);
        }
    }

    @EventHandler
    public void onAnimation(PlayerAnimationEvent event) {
        bump(event.getPlayer().getUniqueId(), 2);
    }

    @EventHandler
    public void onInteract(PlayerInteractEvent event) {
        Action action = event.getAction();
        if (action == Action.LEFT_CLICK_AIR || action == Action.RIGHT_CLICK_AIR) {
            bump(event.getPlayer().getUniqueId(), 3);
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        counts.remove(event.getPlayer().getUniqueId());
    }

    /** Netty-поток: пакет взмаха. */
    public void recordPacketSwing(UUID uuid) {
        bump(uuid, 4);
    }

    /** Netty-поток: пакет атаки. */
    public void recordPacketAttack(UUID uuid) {
        bump(uuid, 5);
    }

    private void bump(UUID uuid, int index) {
        counts.computeIfAbsent(uuid, key -> new long[6])[index]++;
    }

    /** Сводка по игроку со сбросом (дельта между запросами). */
    public String report(Player target) {
        long[] counters = counts.remove(target.getUniqueId());
        if (counters == null) {
            return "нет данных (игрок неактивен)";
        }
        String report = "движ=" + counters[0] + " удары=" + counters[1]
                + " взмахи=" + counters[2] + " клики=" + counters[3];
        if (counters[4] + counters[5] > 0) {
            report += " пвзмахи=" + counters[4] + " пудары=" + counters[5];
        }
        return report;
    }
}
