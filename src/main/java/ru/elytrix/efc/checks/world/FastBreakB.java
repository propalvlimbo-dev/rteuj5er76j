package ru.elytrix.efc.checks.world;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.block.Block;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockDamageEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.BlockUtil;

/**
 * FastBreak.B: баланс задержки между блоками (половина Grim FastBreak).
 * После не-мгновенного блока (копка дольше 100 мс) честный клиент
 * ждёт ~300 мс до следующего старта. Инста-копка правилом не судится.
 * Портировано из Grim (GPL-3.0), адаптировано под Bukkit-события.
 */
public final class FastBreakB extends Check {

    private final Map<UUID, Map<String, Long>> start = new ConcurrentHashMap<>();
    private final Map<UUID, Long> lastFinish = new ConcurrentHashMap<>();
    private final Map<UUID, Long> lastDuration = new ConcurrentHashMap<>();
    private final Map<UUID, Double> delayBalance = new ConcurrentHashMap<>();

    public FastBreakB(ElytrixFuckCheats plugin) {
        super(plugin, "FastBreak", "B", Category.WORLD);
    }

    @Override
    public void onQuit(UUID uuid) {
        start.remove(uuid);
        lastFinish.remove(uuid);
        lastDuration.remove(uuid);
        delayBalance.remove(uuid);
        BlockUtil.clear(uuid);
    }

    @EventHandler
    public void onDamage(BlockDamageEvent event) {
        Player player = event.getPlayer();
        Block block = event.getBlock();
        if (player == null || block == null) {
            return;
        }
        UUID id = player.getUniqueId();
        long now = System.currentTimeMillis();
        long finish = lastFinish.getOrDefault(id, 0L);
        long duration = lastDuration.getOrDefault(id, 0L);
        if (finish != 0 && duration >= 100) {
            long delay = now - finish;
            double bal = delayBalance.getOrDefault(id, 0.0);
            if (delay >= 275) {
                bal *= 0.9;
            } else {
                bal += 300 - delay;
            }
            delayBalance.put(id, bal);
            if (bal > 1000) {
                flag(plugin.getDataManager().get(player), "delay=" + delay + "ms");
            }
        }
        Map<String, Long> positions =
                start.computeIfAbsent(id, key -> new HashMap<>());
        if (positions.size() > 2000) {
            positions.clear();
        }
        positions.put(key(block), now);
    }

    @EventHandler
    public void onBreak(BlockBreakEvent event) {
        Player player = event.getPlayer();
        Block block = event.getBlock();
        if (player == null || block == null) {
            return;
        }
        UUID id = player.getUniqueId();
        BlockUtil.noteBreak(id);
        long now = System.currentTimeMillis();
        Map<String, Long> positions = start.get(id);
        if (positions != null) {
            Long started = positions.remove(key(block));
            if (started != null) {
                lastDuration.put(id, now - started);
            }
        }
        lastFinish.put(id, now);
    }

    private static String key(Block block) {
        return block.getX() + "," + block.getY() + "," + block.getZ();
    }
}
