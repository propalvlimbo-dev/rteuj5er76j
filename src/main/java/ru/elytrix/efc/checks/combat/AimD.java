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
 * Aim.D: замок оси (порт Medusa AimAssistA).
 * Поворот по одной оси с замороженной второй (&lt;0.007) 20 пакетов подряд —
 * так доводит аим, живая рука дрожит. Пороги Medusa один в один.
 * Плюс наш гейт: только в бою (удар в последние 3 сек), транспорт мимо.
 */
public final class AimD extends Check {

    private final Map<UUID, Integer> streaks = new ConcurrentHashMap<>();

    public AimD(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "D", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        streaks.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player.isInsideVehicle()) {
            return;
        }
        UUID uuid = player.getUniqueId();
        long now = System.currentTimeMillis();
        if (now - plugin.getDataManager().get(player).getLastAttack() > 3000) {
            streaks.remove(uuid);
            return;
        }
        float deltaYaw = wrap((float) Math.abs(event.getTo().getYaw() - event.getFrom().getYaw()));
        float deltaPitch = (float) Math.abs(event.getTo().getPitch() - event.getFrom().getPitch());
        if (deltaYaw == 0 && deltaPitch == 0) {
            return;
        }
        float pitch = Math.abs(event.getTo().getPitch());
        boolean invalid = ((deltaPitch < 0.007f && deltaYaw > 3 && deltaYaw < 35)
                || (deltaYaw < 0.007f && deltaPitch > 3 && deltaPitch < 35))
                && pitch < 89;
        if (invalid) {
            int streak = streaks.merge(uuid, 1, Integer::sum);
            if (streak > 20) {
                streaks.remove(uuid);
                flag(plugin.getDataManager().get(player), "axis");
            }
        } else {
            streaks.remove(uuid);
        }
    }

    private static float wrap(float delta) {
        double wrapped = delta % 360;
        if (wrapped > 180) {
            wrapped = 360 - wrapped;
        }
        return (float) wrapped;
    }
}
