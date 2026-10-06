/-! Spec of the PQ2_0 block (ggml type 142): 128 weights, one fp16 scale `d`, 32 bytes of 2-bit codes.
    Value of element j is (code j - 1) * d, with code j = bits [2*(j%4), +2) of byte j/4 (ggml `dequantize_row_pq2_0`).
    Scalars are modelled as Int, so this covers the exact algebra the kernels use; float rounding is out of scope. -/

def QK : Nat := 128

/-- Two-bit code of element `j`, given the block's bytes. -/
def code (qs : Nat → Nat) (j : Nat) : Nat := (qs (j / 4) / 2 ^ (2 * (j % 4))) % 4

/-- Decoded weight, as in CUDA `dequantize_pq2_0`. -/
def weight (d : Int) (qs : Nat → Nat) (j : Nat) : Int := ((code qs j : Int) - 1) * d

def sumTo (f : Nat → Int) : Nat → Int
  | 0 => 0
  | n + 1 => sumTo f n + f n

theorem code_lt (qs : Nat → Nat) (j : Nat) : code qs j < 4 := Nat.mod_lt _ (by decide)

/-- The decoded level is in {-1, 0, 1, 2}; ternary data uses only {-1, 0, 1}, but code 3 decodes to +2 as in ggml. -/
theorem level_range (qs : Nat → Nat) (j : Nat) : -1 ≤ (code qs j : Int) - 1 ∧ (code qs j : Int) - 1 ≤ 2 := by
  have := code_lt qs j
  omega

theorem sumTo_const_mul (d : Int) (g : Nat → Int) (n : Nat) :
    sumTo (fun j => d * g j) n = d * sumTo g n := by
  induction n with
  | zero => simp [sumTo]
  | succ n ih => simp [sumTo, ih, Int.mul_add]

theorem sumTo_congr (f g : Nat → Int) (h : ∀ j, f j = g j) (n : Nat) : sumTo f n = sumTo g n := by
  induction n with
  | zero => rfl
  | succ n ih => simp [sumTo, ih, h]

/-- Fused kernel and CUDA `vec_dot_pq2_0_q8_1`: sum the integer levels against the activations, scale once per block. -/
theorem dot_scale_once (d : Int) (qs : Nat → Nat) (x : Nat → Int) :
    sumTo (fun j => weight d qs j * x j) QK = d * sumTo (fun j => ((code qs j : Int) - 1) * x j) QK := by
  rw [← sumTo_const_mul]
  apply sumTo_congr
  intro j
  simp only [weight]
  rw [Int.mul_comm _ d, Int.mul_assoc]

theorem sumTo_add (f : Nat → Int) (m n : Nat) :
    sumTo f (m + n) = sumTo f m + sumTo (fun k => f (m + k)) n := by
  induction n with
  | zero => simp [sumTo]
  | succ n ih =>
    rw [← Nat.add_assoc]
    simp only [sumTo, ih, Int.add_assoc]

/-- Splitting `a * b` elements into `a` chunks of `b`: the lane decomposition of the Metal kernel (4 lanes x 32). -/
theorem sumTo_chunks (f : Nat → Int) (a b : Nat) :
    sumTo f (a * b) = sumTo (fun i => sumTo (fun k => f (b * i + k)) b) a := by
  induction a with
  | zero => simp [sumTo]
  | succ a ih =>
    have h : (a + 1) * b = a * b + b := Nat.succ_mul a b
    rw [h, sumTo_add, ih]
    simp only [sumTo, Nat.mul_comm a b]

/-- 128 elements = 4 lanes x 32 elements, with the partial sums combined by `simd_sum`. -/
theorem block_lanes (f : Nat → Int) :
    sumTo f QK = sumTo (fun l => sumTo (fun k => f (32 * l + k)) 32) 4 := by
  have := sumTo_chunks f 4 32
  simpa [QK] using this
