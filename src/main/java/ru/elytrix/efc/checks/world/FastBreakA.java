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
 * FastBreak.A: блок сломан без начала копания.
 * Честный клиент всегда шлёт START_DIGGING (BlockDamageEvent) раньше FINISH,
 * даже на инста-копке и даже на обсидиане. Слом без damage = рисованный пакет.
 */
public final class FastBreakA extends Check {

    private final Map<UUID, Map<String, Long>> damage = new ConcurrentHashMap<>();

    public FastBreakA(ElytrixFuckCheats plugin) {
        super(plugin, "FastBreak", "A", Category.WORLD);
    }

    @Override
    public void onQuit(UUID uuid) {
        damage.remove(uuid);
        BlockUtil.clear(uuid);
    }

    @EventHandler
    public void onDamage(BlockDamageEvent event) {
        Player player = event.getPlayer();
        Block block = event.getBlock();
        if (player == null || block == null) {
            return;
        }
        Map<String, Long> positions =
                damage.computeIfAbsent(player.getUniqueId(), key -> new HashMap<>());
        if (positions.size() > 2000) {
            positions.clear();
        }
        positions.put(key(block), System.currentTimeMillis());
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
        Map<String, Long> positions = damage.get(id);
        if (positions != null && positions.containsKey(key(block))) {
            return;
        }
        event.setCancelled(true);
        flag(plugin.getDataManager().get(player), "no-dig break");
    }

    private static String key(Block block) {
        return block.getX() + "," + block.getY() + "," + block.getZ();
    }
}
