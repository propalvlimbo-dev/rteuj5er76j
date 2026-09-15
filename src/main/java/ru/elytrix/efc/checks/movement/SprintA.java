package ru.elytrix.efc.checks.movement;

import java.lang.reflect.Method;
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
 * Sprint.A: невозможные состояния спринта (набор NCP/Grim).
 * Ванилла запрещает спринтовать: присев, с поднятым щитом,
 * с натянутым луком/едой в руках, с голодом 6 и ниже.
 * Читы KeepSprint/OmniSprint/NoSlow эти запреты снимают.
 * Буфер 4 движения (~200 мс) перекрывает рассинхрон 1-3 тика,
 * поэтому честный игрок с лагами сюда не попадает.
 * Полёт/транспорт исключены вручную, кик — своим max-vl.
 */
public final class SprintA extends Check {

    private static final int BUFFER = 4;

    private static final class State {
        int sneak;
        int block;
        int use;
        int hunger;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    private volatile Method handRaisedMethod;
    private volatile boolean handRaisedProbed;
    private volatile Method flyingMethod;
    private volatile boolean flyingProbed;
    private volatile Method glidingMethod;
    private volatile boolean glidingProbed;

    public SprintA(ElytrixFuckCheats plugin) {
        super(plugin, "Sprint", "A", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        if (!player.isSprinting() || player.isInsideVehicle() || isFlying(player)) {
            decay(state);
            return;
        }
        check(player, state, "sneak", player.isSneaking(), 0);
        check(player, state, "block", player.isBlocking(), 1);
        check(player, state, "use", isHandRaised(player), 2);
        check(player, state, "hunger", player.getFoodLevel() <= 6, 3);
    }

    private void check(Player player, State state, String detail, boolean bad, int slot) {
        int value = get(state, slot);
        if (bad) {
            value++;
            if (value >= BUFFER) {
                value = 0;
                flag(plugin.getDataManager().get(player), detail);
            }
        } else if (value > 0) {
            value--;
        }
        set(state, slot, value);
    }

    private static int get(State state, int slot) {
        switch (slot) {
            case 0:
                return state.sneak;
            case 1:
                return state.block;
            case 2:
                return state.use;
            default:
                return state.hunger;
        }
    }

    private static void set(State state, int slot, int value) {
        switch (slot) {
            case 0:
                state.sneak = value;
                break;
            case 1:
                state.block = value;
                break;
            case 2:
                state.use = value;
                break;
            default:
                state.hunger = value;
                break;
        }
    }

    private static void decay(State state) {
        if (state.sneak > 0) {
            state.sneak--;
        }
        if (state.block > 0) {
            state.block--;
        }
        if (state.use > 0) {
            state.use--;
        }
        if (state.hunger > 0) {
            state.hunger--;
        }
    }

    private boolean isFlying(Player player) {
        return callBoolean(player, "isFlying", true) || callBoolean(player, "isGliding", false);
    }

    private boolean isHandRaised(Player player) {
        return callBoolean(player, "isHandRaised", false);
    }

    /**
     * Методы есть в API не везде одинаково — дергаем рефлексией,
     * при неудаче возвращаем безопасное значение.
     */
    private boolean callBoolean(Player player, String name, boolean slot) {
        try {
            Method cached;
            if ("isHandRaised".equals(name)) {
                if (!handRaisedProbed) {
                    handRaisedProbed = true;
                    handRaisedMethod = probe(player, name);
                }
                cached = handRaisedMethod;
            } else if ("isFlying".equals(name)) {
                if (!flyingProbed) {
                    flyingProbed = true;
                    flyingMethod = probe(player, name);
                }
                cached = flyingMethod;
            } else {
                if (!glidingProbed) {
                    glidingProbed = true;
                    glidingMethod = probe(player, name);
                }
                cached = glidingMethod;
            }
            if (cached == null) {
                return false;
            }
            Object value = cached.invoke(player);
            return value instanceof Boolean && (Boolean) value;
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static Method probe(Player player, String name) {
        try {
            return player.getClass().getMethod(name);
        } catch (Throwable ignored) {
            try {
                return Player.class.getMethod(name);
            } catch (Throwable ignored2) {
                return null;
            }
        }
    }
}
