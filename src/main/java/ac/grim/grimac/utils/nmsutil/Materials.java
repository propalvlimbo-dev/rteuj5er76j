package ac.grim.grimac.utils.nmsutil;

import com.github.retrooper.packetevents.protocol.world.states.type.StateType;
import com.github.retrooper.packetevents.protocol.world.states.type.StateTypes;

/**
 * EFC-совместимость: Grim Materials (только используемые методы).
 */
public final class Materials {

    private Materials() {
    }

    public static boolean isNoPlaceLiquid(StateType type) {
        return type == StateTypes.WATER || type == StateTypes.LAVA || type == StateTypes.BUBBLE_COLUMN;
    }
}
