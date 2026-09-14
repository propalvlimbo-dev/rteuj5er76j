package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerAnimationEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * KillAura.B: удар без взмаха рукой (silent / no-swing аура).
 * Честный клиент всегда шлёт анимацию перед ударом.
 */
public final class KillAuraB extends Check {

    private final Map<UUID, Long> lastSwing = new ConcurrentHashMap<>();

    public KillAuraB(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "B", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        lastSwing.remove(uuid);
    }

    @EventHandler
    public void onAnimation(PlayerAnimationEvent event) {
        lastSwing.put(event.getPlayer().getUniqueId(), System.currentTimeMillis());
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        long now = System.currentTimeMillis();
        Long swing = lastSwing.get(attacker.getUniqueId());
        if (swing == null) {
            // Первый удар без истории — прощаем, дальше следим.
            lastSwing.put(attacker.getUniqueId(), now);
            return;
        }
        if (now - swing > 300) {
            flag(plugin.getDataManager().get(attacker), "no-swing");
        }
    }
}
