package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Material;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerVelocityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.BlockUtil;
import ru.elytrix.efc.util.MovementUtil;

/**
 * Jesus.A: ходьба по воде/лаве — ноги в воздухе, под ногами жидкость,
 * вертикаль почти ноль, горизонталь есть. 10 движений подряд.
 * Прыжки, плавание, кувшинки, лодки, фрост-волкер — мимо.
 */
public final class JesusA extends Check {

    private final Map<UUID, Integer> ticks = new ConcurrentHashMap<>();

    public JesusA(ElytrixFuckCheats plugin) {
        super(plugin, "Jesus", "A", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        ticks.remove(uuid);
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
            ticks.remove(id);
            return;
        }
        Material feet = MovementUtil.feetType(player);
        Material below = MovementUtil.belowType(player);
        if (!BlockUtil.isAir(feet) || !MovementUtil.isLiquid(below)) {
            ticks.remove(id);
            return;
        }
        if (event.getFrom() == null || event.getTo() == null) {
            return;
        }
        double dy = event.getTo().getY() - event.getFrom().getY();
        double dx = event.getTo().getX() - event.getFrom().getX();
        double dz = event.getTo().getZ() - event.getFrom().getZ();
        double dxz = Math.sqrt(dx * dx + dz * dz);
        if (Math.abs(dy) < 0.03 && dxz > 0.05) {
            int count = ticks.getOrDefault(id, 0) + 1;
            ticks.put(id, count);
            if (count % 10 == 0) {
                flag(plugin.getDataManager().get(player), "waterwalk=" + count + "t");
            }
            return;
        }
        ticks.remove(id);
    }
}
