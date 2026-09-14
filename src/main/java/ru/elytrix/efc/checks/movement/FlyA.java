package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Material;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Fly.A: полёт без крыльев — долгий подъём вверх или зависание в воздухе.
 * Прыжок даёт максимум ~5 тиков роста, дальше гравитация. Чит растёт дольше
 * или висит на месте. Лестницы, лозы, леса, вода, лава, паутина не флагаются.
 */
public final class FlyA extends Check {

    private static final class State {
        int airTicks;
        int upTicks;
        int hoverTicks;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public FlyA(ElytrixFuckCheats plugin) {
        super(plugin, "Fly", "A", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        if (player.isGliding() || player.isInsideVehicle() || player.isInWater()
                || isClimbable(event.getTo().getBlock().getType())) {
            reset(state);
            return;
        }
        if (player.isOnGround()) {
            reset(state);
            return;
        }
        double dy = event.getTo().getY() - event.getFrom().getY();
        state.airTicks++;
        if (state.airTicks < 8) {
            return;
        }
        if (dy > 0.05) {
            state.upTicks++;
        } else {
            state.upTicks = 0;
        }
        if (Math.abs(dy) < 0.005) {
            state.hoverTicks++;
        } else {
            state.hoverTicks = 0;
        }
        if (state.upTicks > 6) {
            state.upTicks = 0;
            flag(plugin.getDataManager().get(player), "ascend");
        } else if (state.hoverTicks > 12) {
            state.hoverTicks = 0;
            flag(plugin.getDataManager().get(player), "hover");
        }
    }

    private static void reset(State state) {
        state.airTicks = 0;
        state.upTicks = 0;
        state.hoverTicks = 0;
    }

    private static boolean isClimbable(Material material) {
        return material == Material.LADDER
                || material == Material.VINE
                || material == Material.TWISTING_VINES
                || material == Material.WEEPING_VINES
                || material == Material.SCAFFOLDING
                || material == Material.WATER
                || material == Material.LAVA
                || material == Material.COBWEB;
    }
}
