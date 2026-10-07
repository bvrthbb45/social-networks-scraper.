package app.opsec.monitor

import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/** First run (or "change server"): ask for the address of the unit's server. HTTPS only. */
class ConnectActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)

        val pad = (24 * resources.displayMetrics.density).toInt()
        val title = TextView(this).apply {
            text = getString(R.string.connect_title)
            textSize = 22f
        }
        val help = TextView(this).apply { text = getString(R.string.connect_help) }
        val input = EditText(this).apply {
            hint = getString(R.string.connect_hint)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            gravity = Gravity.START
            setSingleLine()
        }
        val error = TextView(this).apply {
            setTextColor(0xFFB42318.toInt())
            visibility = View.GONE
        }
        val button = Button(this).apply { text = getString(R.string.connect_button) }

        button.setOnClickListener {
            val origin = ServerAddress.parse(input.text.toString(), allowLoopbackCleartext = BuildConfig.DEBUG)
            if (origin == null) {
                error.text = getString(R.string.error_invalid_address)
                error.visibility = View.VISIBLE
            } else {
                ServerStore.set(this, origin)
                startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
                finish()
            }
        }

        setContentView(
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(pad, pad, pad, pad)
                addView(title)
                addView(help)
                addView(input)
                addView(error)
                addView(button)
            },
        )
    }
}
