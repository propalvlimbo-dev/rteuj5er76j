package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.Action;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerItemConsumeEvent;
import org.bukkit.inventory.ItemStack;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * FastEat.A: съедено быстрее 0.9 сек. Честно — 1.6 сек, лаги только тянут время.
 */
public final class FastEatA extends Check {

    private final Map<UUID, Long> eats = new ConcurrentHashMap<>();

    public FastEatA(ElytrixFuckCheats plugin) {
        super(plugin, "FastEat", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        eats.remove(uuid);
    }

    @EventHandler
    public void onInteract(PlayerInteractEvent event) {
        Action action = event.getAction();
        if (action != Action.RIGHT_CLICK_AIR && action != Action.RIGHT_CLICK_BLOCK) {
            return;
        }
        ItemStack item = event.getItem();
        if (item == null || !item.getType().isEdible()) {
            return;
        }
        eats.put(event.getPlayer().getUniqueId(), System.currentTimeMillis());
    }

    @EventHandler
    public void onConsume(PlayerItemConsumeEvent event) {
        Player player = event.getPlayer();
        Long start = eats.remove(player.getUniqueId());
        if (start == null) {
            return;
        }
        long took = System.currentTimeMillis() - start;
        if (took < 900) {
            flag(plugin.getDataManager().get(player), "fast " + took + "ms");
        }
    }
}
