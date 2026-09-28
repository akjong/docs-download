
# Develop a hook
 
In this guide, we'll develop a hook for concentrated liquidity pool. The same step will apply for liquidity book. We'll start with introducing hook template before the step by step guide section.
 
## Hooks template
 
Proceed to [https://github.com/pancakeswap/infinity-hooks-template](https://github.com/pancakeswap/infinity-hooks-template) for the hook template. Click `Use this template` to create a new repository based on the template.
 
The template requires Foundry. If you don't have Foundry installed, please follow the [installation guide](https://book.getfoundry.sh/getting-started/installation) .
 
Once the new repository is cloned to local setup, run the following commands:
 
```
> forge install // install dependencies
> forge test // run the existing tests in the repository
```
 
Within both `src` and `test` there are 2 folders: `pool-cl` and `pool-bin` . If you are developing for concentrated liquidity pool, focus on pool-cl folder, otherwise pool-bin folder for the liquidity book pool type.
 
### BaseHook
 
BaseHook is a base contract where you will inherit for your hooks. It provides
 
1. helper method: `_hooksRegistrationBitmapFrom` to set up the callback required 
2. callback method: for you to overwrite 
 
```
// Snippet from CLCounterHook.sol
import {CLBaseHook} from "./CLBaseHook.sol";
 
contract CLCounterHook is CLBaseHook {
 
  constructor(ICLPoolManager _poolManager) CLBaseHook(_poolManager) {}
 
  // 1. Set up callback required. in this case, 4 callback are required
  function getHooksRegistrationBitmap() external pure override returns (uint16) {
    return _hooksRegistrationBitmapFrom(
        Permissions({
            beforeInitialize: false,
            afterInitialize: false,
            beforeAddLiquidity: true,
            afterAddLiquidity: true,
            beforeRemoveLiquidity: false,
            afterRemoveLiquidity: false,
            beforeSwap: true,
            afterSwap: true,
            beforeDonate: false,
            afterDonate: false,
            beforeSwapReturnDelta: false,
            afterSwapReturnDelta: false,
            afterAddLiquidityReturnDelta: false,
            afterRemoveLiquidityReturnDelta: false
        })
    );
  }
 
  // 2. For each callback required, overwrite the method
  function _beforeAddLiquidity(address, PoolKey calldata key, ICLPoolManager.ModifyLiquidityParams calldata, bytes calldata)
    external override poolManagerOnly returns (bytes4) {
      // implement hook logic and then return selector
      return this.beforeAddLiquidity.selector;
  }
}
 
```
 
## Step by step guide
 
We will develop a hook that allows [veCake](https://docs.pancakeswap.finance/products/vecake/what-is-vecake) holder to get a 50% swap fee discount when swapping through pool with this hook.
 
---
 
### Step 1: Download hook template
 
1. Create a new repository from pancake-infinity-hooks-template: [Click here](https://github.com/new?template_name=infinity-hooks-template&template_owner=pancakeswap) 
2. Clone the repository locally and run `forge install` and `forge test` to verify local setup. 
 
---
 
### Step 2: Implementation idea
 
The flow will be as follows:
 
1. We first initialize the pool via `poolManager.function initialize(PoolKey memory key, uint160 sqrtPriceX96)` , the default swap fee for the pool is by default 0. 
2. We will then call `hook.setLpFee(PoolKey memory key, uint24 lpFee)` to set the default swap fee for the pool. 
3. At `beforeSwap()` , hook check if the swapper is veCake holder and return the updated swap fee accordingly through `lpFeeOverride` value. 
 

![Store default swap fee in hook](https://developer.pancakeswap.finance/infinity/guides-develop-hook-3.png)

 
---
 
### Step 3: Implement the hook
 
We'll perform the following:
 
1. Add `beforeSwap` permission 
2. Implement `setLpFee()` 
3. Return the swap fee based on whether user is veCake holder in `beforeSwap` 
 
Let's go through the implementation step by step
 
#### 3.1 AddbeforeSwappermission
 
Create a file called at `src/pool-cl/VeCakeSwapDiscountHook.sol` and implement the following. The hook contract extends `CLBaseHook` .
 
```
contract VeCakeSwapDiscountHook is CLBaseHook { 
    function getHooksRegistrationBitmap() external pure override returns (uint16) {
        return _hooksRegistrationBitmapFrom(
            Permissions({
                beforeInitialize: false,
                afterInitialize: false, 
                beforeAddLiquidity: false,
                afterAddLiquidity: false,
                beforeRemoveLiquidity: false,
                afterRemoveLiquidity: false,
                beforeSwap: true, 
                afterSwap: false,
                beforeDonate: false,
                afterDonate: false,
                beforeSwapReturnsDelta: false,
                afterSwapReturnsDelta: false,
                afterAddLiquidityReturnsDelta: false,
                afterRemoveLiquidityReturnsDelta: false
            })
        );
    }
}
```
 
#### 3.2 ImplementsetLpFee()
 
Note that in production, you will want to ensure only authorized user can call `setLpFee`
 
```
// mapping to store poolId 
mapping(PoolId => uint24) public poolIdToLpFee;
 
/// @notice Update the lp fee for a pool
/// @dev warning: in production, ensure this function is only callable by authorized user
function setLpFee(PoolKey calldata key, uint24 lpFee) external {
  poolIdToLpFee[key.toId()] = lpFee;
}
```
 
#### 3.3 Return the lp fee based on whether user is veCake holder inbeforeSwap
 
`beforeSwap` will be called before a swap happens, and the third return value `uint24 lpFeeOverride` is where we can override the swap fee.
 
Note the return value need to include `LPFeeLibrary.OVERRIDE_FEE_FLAG` so pool manager knows the intention is to override swap fee.
 
```
function beforeSwap(address, PoolKey calldata key, ICLPoolManager.SwapParams calldata, bytes calldata)
    external view override poolManagerOnly returns (bytes4, BeforeSwapDelta, uint24)
{
    uint24 lpFee = poolIdToLpFee[key.toId()];
 
    if (veCake.balanceOf(tx.origin) >= 1 ether) {
        lpFee = lpFee / 2; 
    }
 
    return (this.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, lpFee | LPFeeLibrary.OVERRIDE_FEE_FLAG);
}
```
 View complete source code here File src/pool-cl/VeCakeSwapDiscountHook.sol 
```
// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.24;
 
import {PoolKey} from "infinity-core/src/types/PoolKey.sol";
import {LPFeeLibrary} from "infinity-core/src/libraries/LPFeeLibrary.sol";
import {BeforeSwapDelta, BeforeSwapDeltaLibrary} from "infinity-core/src/types/BeforeSwapDelta.sol";
import {PoolId, PoolIdLibrary} from "infinity-core/src/types/PoolId.sol";
import {ICLPoolManager} from "infinity-core/src/pool-cl/interfaces/ICLPoolManager.sol";
import {CLBaseHook} from "./CLBaseHook.sol";
 
interface IVeCake {
    function balanceOf(address account) external view returns (uint256 balance);
}
 
/// @notice VeCakeSwapDiscountHook provides 50% swap fee discount for veCake holder
/// Idea:
///   1. PancakeSwap has veCake (vote-escrowed Cake), user obtain veCake by locking cake
///   2. If the swapper holds veCake, provide 50% swap fee discount
/// Implementation:
///   1. When pool is initialized, at `afterInitialize` we store what is the intended swap fee for the pool
//    2. During `beforeSwap` callback, the hook checks if users is veCake holder and provide discount accordingly
contract VeCakeSwapDiscountHook is CLBaseHook {
    using PoolIdLibrary for PoolKey;
    using LPFeeLibrary for uint24;
 
    IVeCake public veCake;
    mapping(PoolId => uint24) public poolIdToLpFee;
 
    constructor(ICLPoolManager _poolManager, address _veCake) CLBaseHook(_poolManager) {
        veCake = IVeCake(_veCake);
    }
 
    function getHooksRegistrationBitmap() external pure override returns (uint16) {
        return _hooksRegistrationBitmapFrom(
            Permissions({
                beforeInitialize: false,
                afterInitialize: false,
                beforeAddLiquidity: false,
                afterAddLiquidity: false,
                beforeRemoveLiquidity: false,
                afterRemoveLiquidity: false,
                beforeSwap: true,
                afterSwap: false,
                beforeDonate: false,
                afterDonate: false,
                beforeSwapReturnDelta: false,
                afterSwapReturnDelta: false,
                afterAddLiquidityReturnDelta: false,
                afterRemoveLiquidityReturnDelta: false
            })
        );
    }
 
    /// @notice The hook called before a swap
    /// @return bytes4 The function selector for the hook
    /// @return BeforeSwapDelta The hook's delta in specified and unspecified currencies.
    /// @return uint24 Optionally override the lp fee, only used if three conditions are met:
    ///     1) the Pool has a dynamic fee,
    ///     2) the value's override flag is set to 1 i.e. vaule & OVERRIDE_FEE_FLAG = 0x400000 != 0
    ///     3) the value is less than or equal to the maximum fee (1 million)
    function _beforeSwap(address, PoolKey calldata key, ICLPoolManager.SwapParams calldata, bytes calldata)
        internal
        override
        returns (bytes4, BeforeSwapDelta, uint24)
    {
        uint24 lpFee = poolIdToLpFee[key.toId()];
 
        /// If veCake holder, lpFee is half
        if (veCake.balanceOf(tx.origin) >= 1 ether) {
            lpFee = poolIdToLpFee[key.toId()] / 2;
        }
 
        return (this.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, lpFee | LPFeeLibrary.OVERRIDE_FEE_FLAG);
    }
 
    /// @notice Update the lp fee for a pool
    /// @dev warning: in production, ensure this function is only callable by authorized user
    function setLpFee(PoolKey calldata key, uint24 lpFee) external {
        poolIdToLpFee[key.toId()] = lpFee;
    }
}
```
 
---
 
### Step 4: Add Hook test
 
In the test, we'll test 2 scenarios:
 
1. when swapping as a normal user 
2. when swapping as a veCake holder 
 
Create a file called at `test/pool-cl/VeCakeSwapDiscountHook.t.sol` and copy content from below.
 View complete source code here 
> **Note:** The assertion in the test has been simplified, in the real world, you should calculate the `amtOut` and verify it.
 File test/pool-cl/VeCakeSwapDiscountHook.t.sol 
```
// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.24;
 
import {MockERC20} from "solmate/src/test/utils/mocks/MockERC20.sol";
import {Test} from "forge-std/Test.sol";
import {Constants} from "infinity-core/test/pool-cl/helpers/Constants.sol";
import {Currency} from "infinity-core/src/types/Currency.sol";
import {PoolKey} from "infinity-core/src/types/PoolKey.sol";
import {LPFeeLibrary} from "infinity-core/src/libraries/LPFeeLibrary.sol";
import {CLPoolParametersHelper} from "infinity-core/src/pool-cl/libraries/CLPoolParametersHelper.sol";
import {VeCakeSwapDiscountHook} from "../../src/pool-cl/VeCakeSwapDiscountHook.sol";
import {CLTestUtils} from "./utils/CLTestUtils.sol";
import {PoolIdLibrary} from "infinity-core/src/types/PoolId.sol";
import {ICLRouterBase} from "infinity-periphery/src/pool-cl/interfaces/ICLRouterBase.sol";
 
import {console2} from "forge-std/console2.sol";
 
contract VeCakeSwapDiscountHookTest is Test, CLTestUtils {
    using PoolIdLibrary for PoolKey;
    using CLPoolParametersHelper for bytes32;
 
    VeCakeSwapDiscountHook hook;
    Currency currency0;
    Currency currency1;
    PoolKey key;
    MockERC20 veCake = new MockERC20("veCake", "veCake", 18);
    address alice = makeAddr("alice");
 
    function setUp() public {
        (currency0, currency1) = deployContractsWithTokens();
        hook = new VeCakeSwapDiscountHook(poolManager, address(veCake));
 
        // create the pool key
        key = PoolKey({
            currency0: currency0,
            currency1: currency1,
            hooks: hook,
            poolManager: poolManager,
            fee: LPFeeLibrary.DYNAMIC_FEE_FLAG,
            parameters: bytes32(uint256(hook.getHooksRegistrationBitmap())).setTickSpacing(10)
        });
 
        // initialize pool at 1:1 price point and set 3000 (0.3%) as lp fee, lpFee is stored in the hook
        poolManager.initialize(key, Constants.SQRT_RATIO_1_1);
        hook.setLpFee(key, 3000);
 
        // add liquidity so that swap can happen
        MockERC20(Currency.unwrap(currency0)).mint(address(this), 100 ether);
        MockERC20(Currency.unwrap(currency1)).mint(address(this), 100 ether);
        addLiquidity(key, 100 ether, 100 ether, -60, 60, address(this));
 
        // approve from alice for swap in the test cases below
        permit2Approve(alice, currency0, address(universalRouter));
        permit2Approve(alice, currency1, address(universalRouter));
 
        // mint alice token for trade later
        MockERC20(Currency.unwrap(currency0)).mint(address(alice), 100 ether);
    }
 
    function testNonVeCakeHolder() public {
        uint256 amtOut = _swap();
 
        // amt out be at least 0.3% lesser due to swap fee
        assertLe(amtOut, 0.997 ether);
    }
 
    function testVeCakeHolder() public {
        // mint alice veCake
        veCake.mint(address(alice), 1 ether);
 
        uint256 amtOut = _swap();
 
        // amtOut should a bit lesser than 0.9985 due to 0.15% swap fee
        assertLe(amtOut, 0.9985 ether);
        assertGe(amtOut, 0.997 ether);
    }
 
    function _swap() internal returns (uint256 amtOut) {
        uint256 amt1BalBefore = MockERC20(Currency.unwrap(currency1)).balanceOf(address(alice));
 
        // set alice as tx.origin
        vm.prank(address(alice), address(alice));
        exactInputSingle(
            ICLRouterBase.CLSwapExactInputSingleParams({
                poolKey: key,
                zeroForOne: true,
                amountIn: 1 ether,
                amountOutMinimum: 0,
                hookData: new bytes(0)
            })
        );
 
        uint256 amt1BalAfter = MockERC20(Currency.unwrap(currency1)).balanceOf(address(alice));
        amtOut = amt1BalAfter - amt1BalBefore;
    }
}
```
 
In order to allow dynamic swap fee, the `fee` variable in poolKey must have dynamic flag set.
 
```
key = PoolKey({
    currency0: currency0,
    currency1: currency1,
    hooks: hook,
    poolManager: poolManager,
    fee: LPFeeLibrary.DYNAMIC_FEE_FLAG, 
    parameters: bytes32(uint256(hook.getHooksRegistrationBitmap())).setTickSpacing(10)
});
```
 
---
 
### Step 5: Verify
 
Run `forge test` to verify test passing.
 
## Next step
 
Explore more guides in our developer documentation:
 
- [Taking a fee via hook](https://developer.pancakeswap.finance/contracts/infinity/guides/hook-examples/taking-fee-via-hook) 
- [Overwrite amm-curve via hook](https://developer.pancakeswap.finance/contracts/infinity/guides/hook-examples/overwriting-amm-curve) 
 
For additional insights, we recommend reading [this blog post by Certik](https://www.certik.com/resources/blog/pancakeswap-infinity-hooks-security-considerations) on security considerations for hooks.
