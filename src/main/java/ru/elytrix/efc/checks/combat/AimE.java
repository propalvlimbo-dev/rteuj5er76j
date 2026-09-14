package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Aim.E: круглые доводки (порт Medusa AimAssistB).
 * Дельта ровно в градус (remainder 0) — скрипт, сетка мыши даёт дроби.
 * Буфер +1/-0.25, флаг на &gt;4 — как у Medusa. Плюс наш гейт: только в бою.
 */
public final class AimE extends Check {

    private final Map<UUID, Double> buffers = new ConcurrentHashMap<>();

    public AimE(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "E", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        buffers.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        UUID uuid = player.getUniqueId();
        long now = System.currentTimeMillis();
        if (now - plugin.getDataManager().get(player).getLastAttack() > 3000) {
            buffers.remove(uuid);
            return;
        }
        float deltaYaw = wrap((float) (event.getTo().getYaw() - event.getFrom().getYaw()));
        float deltaPitch = event.getTo().getPitch() - event.getFrom().getPitch();
        if (deltaYaw == 0 && deltaPitch == 0) {
            return;
        }
        if ((deltaPitch % 1 == 0 || deltaYaw % 1 == 0) && deltaPitch != 0 && deltaYaw != 0) {
            double buffer = buffers.merge(uuid, 1.0, Double::sum);
            if (buffer > 4) {
                buffers.remove(uuid);
                flag(plugin.getDataManager().get(player), "rounded");
            }
        } else {
            buffers.computeIfPresent(uuid, (key, buffer) -> {
                double next = buffer - 0.25;
                return next <= 0 ? null : next;
            });
        }
    }

    private static float wrap(float delta) {
        double wrapped = delta % 360;
        if (wrapped > 180) {
            wrapped -= 360;
        } else if (wrapped < -180) {
            wrapped += 360;
        }
        return (float) wrapped;
    }
}
