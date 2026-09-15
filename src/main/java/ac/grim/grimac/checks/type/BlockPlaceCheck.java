package ac.grim.grimac.checks.type;

import ac.grim.grimac.api.config.ConfigManager;
import ac.grim.grimac.checks.Check;
import ac.grim.grimac.player.GrimPlayer;
import ac.grim.grimac.utils.anticheat.update.BlockPlace;

/**
 * EFC-совместимость: Grim BlockPlaceCheck.
 */
public class BlockPlaceCheck extends Check implements RotationCheck, BlockBreakCheck {

    protected int cancelVL;

    public BlockPlaceCheck(GrimPlayer player) {
        super(player);
    }

    public void onBlockPlace(final BlockPlace place) {
    }

    public void onPostFlyingBlockPlace(BlockPlace place) {
    }

    @Override
    public void onReload(ConfigManager config) {
        this.cancelVL = config.getIntElse(getConfigName() + ".cancelVL", 5);
    }

    protected boolean shouldCancel() {
        return cancelVL >= 0 && violations >= cancelVL;
    }
}
