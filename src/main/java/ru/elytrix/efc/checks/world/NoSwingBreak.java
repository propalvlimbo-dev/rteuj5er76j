package ru.elytrix.efc.checks.world;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockDamageEvent;
import org.bukkit.event.player.PlayerAnimationEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * NoSwingBreak.A: начало копания без взмаха за 150 мс (Grim NoSwingBreak).
 * Честный клиент машет каждый тик копания.
 * Портировано из Grim (GPL-3.0), адаптировано под Bukkit-события.
 */
public final class NoSwingBreak extends Check {

    private final Map<UUID, Long> swings = new ConcurrentHashMap<>();

    public NoSwingBreak(ElytrixFuckCheats plugin) {
        super(plugin, "NoSwingBreak", "A", Category.WORLD);
    }

    @Override
    public void onQuit(UUID uuid) {
        swings.remove(uuid);
    }

    @EventHandler
    public void onSwing(PlayerAnimationEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        swings.put(player.getUniqueId(), System.currentTimeMillis());
    }

    @EventHandler
    public void onDamage(BlockDamageEvent event) {
        Player player = event.getPlayer();
        if (player == null || event.getBlock() == null) {
            return;
        }
        long swing = swings.getOrDefault(player.getUniqueId(), 0L);
        if (System.currentTimeMillis() - swing > 150) {
            event.setCancelled(true);
            flag(plugin.getDataManager().get(player), "no-swing dig");
        }
    }
}
