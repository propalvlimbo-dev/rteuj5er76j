package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Material;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.Action;
import org.bukkit.event.entity.EntityShootBowEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.inventory.ItemStack;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * FastBow.A: выстрел в полную силу быстрее, чем можно натянуть.
 * Честный сильный выстрел требует ~секунду натяжки.
 */
public final class FastBowA extends Check {

    private final Map<UUID, Long> draws = new ConcurrentHashMap<>();

    public FastBowA(ElytrixFuckCheats plugin) {
        super(plugin, "FastBow", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        draws.remove(uuid);
    }

    @EventHandler
    public void onInteract(PlayerInteractEvent event) {
        Action action = event.getAction();
        if (action != Action.RIGHT_CLICK_AIR && action != Action.RIGHT_CLICK_BLOCK) {
            return;
        }
        ItemStack item = event.getItem();
        if (item == null || item.getType() != Material.BOW) {
            return;
        }
        draws.put(event.getPlayer().getUniqueId(), System.currentTimeMillis());
    }

    @EventHandler
    public void onShoot(EntityShootBowEvent event) {
        if (!(event.getEntity() instanceof Player)) {
            return;
        }
        Player player = (Player) event.getEntity();
        Long start = draws.remove(player.getUniqueId());
        if (start == null) {
            return;
        }
        long charge = System.currentTimeMillis() - start;
        if (charge < 200 && event.getForce() > 0.8f) {
            flag(plugin.getDataManager().get(player), "fast " + charge + "ms");
        }
    }
}
