package ru.elytrix.efc.checks.world;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockPlaceEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.packet.PacketData;
import ru.elytrix.efc.util.MovementUtil;

/**
 * Scaffold.B: повтор той же дельты поворота при установках (Grim DuplicateRotPlace).
 * Живая мышь аналоговой дельты дважды не повторяет; бот — повторяет.
 * Флаг за два повтора подряд. Без PacketEvents тихо спит.
 * Портировано из Grim (GPL-3.0), адаптировано под Bukkit-события.
 */
public final class ScaffoldB extends Check {

    private final Map<UUID, Float> lastDelta = new ConcurrentHashMap<>();
    private final Map<UUID, Integer> dups = new ConcurrentHashMap<>();

    public ScaffoldB(ElytrixFuckCheats plugin) {
        super(plugin, "Scaffold", "B", Category.WORLD);
    }

    @Override
    public void onQuit(UUID uuid) {
        lastDelta.remove(uuid);
        dups.remove(uuid);
    }

    @EventHandler
    public void onPlace(BlockPlaceEvent event) {
        Player player = event.getPlayer();
        if (player == null || event.getBlock() == null) {
            return;
        }
        if (MovementUtil.cantCheck(player)) {
            return;
        }
        UUID id = player.getUniqueId();
        long now = System.currentTimeMillis();
        PacketData packets = plugin.getPacketManager().get(id);
        if (!packets.hasRecentFlying(now, 2000)) {
            return;
        }
        float delta = packets.getLastYaw() - packets.getPrevYaw();
        delta = ((delta + 540) % 360) - 180;
        if (Math.abs(delta) <= 2) {
            lastDelta.put(id, delta);
            dups.remove(id);
            return;
        }
        Float prev = lastDelta.get(id);
        lastDelta.put(id, delta);
        if (prev != null && Math.abs(delta - prev) < 0.0001) {
            int count = dups.getOrDefault(id, 0) + 1;
            dups.put(id, count);
            if (count >= 2) {
                dups.remove(id);
                event.setCancelled(true);
                flag(plugin.getDataManager().get(player), "dup-rot");
            }
            return;
        }
        dups.remove(id);
    }
}
