package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.block.Block;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerVelocityEvent;
import org.bukkit.potion.PotionEffectType;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.MovementUtil;

/**
 * Fly.B: зависание (|dy| ~ 0 дольше 12 тиков подряд) и блатентный
 * взлёт (два подъёма &gt; 1.5 подряд — одиночный скачок бывает у хоруса/TP).
 * Пик прыжка даёт 1-2 «плоских» тика и честно сбрасывается.
 */
public final class FlyB extends Check {

    private final Map<UUID, Integer> hoverTicks = new ConcurrentHashMap<>();
    private final Map<UUID, Long> lastRise = new ConcurrentHashMap<>();

    public FlyB(ElytrixFuckCheats plugin) {
        super(plugin, "Fly", "B", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        hoverTicks.remove(uuid);
        lastRise.remove(uuid);
    }

    @EventHandler
    public void onVelocity(PlayerVelocityEvent event) {
        try {
            MovementUtil.noteVelocity(event.getPlayer().getUniqueId());
        } catch (Throwable ignored) {
        }
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        UUID id = player.getUniqueId();
        if (MovementUtil.cantCheck(player) || MovementUtil.velocityRecent(id)) {
            clear(id);
            return;
        }
        if (player.isOnGround()) {
            clear(id);
            return;
        }
        Material feet = MovementUtil.feetType(player);
        Material below = MovementUtil.belowType(player);
        if (MovementUtil.isClimbable(feet) || MovementUtil.isClimbable(below)) {
            clear(id);
            return;
        }
        if (MovementUtil.isLiquid(feet) || MovementUtil.isLiquid(below)) {
            clear(id);
            return;
        }
        if (MovementUtil.isWeb(feet) || MovementUtil.isWeb(below)) {
            clear(id);
            return;
        }
        if (MovementUtil.effectAmplifier(player, PotionEffectType.LEVITATION) >= 0
                || MovementUtil.effectAmplifier(player, PotionEffectType.SLOW_FALLING) >= 0) {
            clear(id);
            return;
        }
        if (MovementUtil.isBounceSafe(feet) || MovementUtil.isBounceSafe(below)) {
            clear(id);
            return;
        }
        if (event.getFrom() == null || event.getTo() == null) {
            return;
        }
        double dy = event.getTo().getY() - event.getFrom().getY();
        long now = System.currentTimeMillis();
        if (dy > 1.5) {
            Long prev = lastRise.get(id);
            lastRise.put(id, now);
            if (prev != null && now - prev < 150) {
                clear(id);
                flag(plugin.getDataManager().get(player), String.format("rise=%.2f", dy));
            }
            return;
        }
        if (Math.abs(dy) < 0.02) {
            int ticks = hoverTicks.getOrDefault(id, 0) + 1;
            hoverTicks.put(id, ticks);
            if (ticks >= 12 && (ticks - 12) % 4 == 0) {
                if (touchesHoney(player)) {
                    clear(id);
                    return;
                }
                flag(plugin.getDataManager().get(player), "hover=" + ticks + "t");
            }
            return;
        }
        hoverTicks.remove(id);
    }

    private void clear(UUID id) {
        hoverTicks.remove(id);
        lastRise.remove(id);
    }

    /** Сползание по мёду выглядит как зависание — проверяем соседние блоки. */
    private static boolean touchesHoney(Player player) {
        try {
            Location loc = player.getLocation();
            double[] dxz = {0, 0.35, -0.35};
            for (double ox : dxz) {
                for (double oz : dxz) {
                    Block block = new Location(loc.getWorld(),
                            loc.getX() + ox, loc.getY(), loc.getZ() + oz).getBlock();
                    if (block != null && block.getType() == Material.HONEY_BLOCK) {
                        return true;
                    }
                }
            }
        } catch (Throwable ignored) {
        }
        return false;
    }
}
